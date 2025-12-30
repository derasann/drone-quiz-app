# app.py  (Streamlit quiz app: normal mode / review mode + weakness ranking + PASS/FAIL per set)
# Compatible with older Streamlit (Python 3.7 env) by using experimental_rerun/cache when needed.

import json
import os
import random
from datetime import datetime

import streamlit as st


# -----------------------------
# Compatibility helpers
# -----------------------------
def rerun():
    """Streamlit rerun compatible across versions."""
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.write("⚠️ rerun is not available in this Streamlit version.")
        st.stop()


# Cache decorator compatible across versions
if hasattr(st, "cache_data"):
    cache_data = st.cache_data
elif hasattr(st, "experimental_memo"):
    cache_data = st.experimental_memo
else:
    cache_data = st.cache  # deprecated in new versions, but works in old ones


# -----------------------------
# Settings
# -----------------------------
QUESTIONS_PATH = "questions.json"   # <-- your questions file
STATS_PATH = "stats.json"           # saved locally (optional)
SET_SIZE = 24                       # 1セット24問
PASS_LINE_24 = 22                   # 24問中22問正解で合格


# -----------------------------
# IO
# -----------------------------
@cache_data(show_spinner=False)
def load_questions(path: str):
    """
    questions.json:
      - list形式: [ {...}, {...} ]
      - dict形式: {"questions":[...]} も許容
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "questions" in data:
        data = data["questions"]

    if not isinstance(data, list):
        raise ValueError("questions.json は「配列(list)」形式である必要があります。例: [ {...}, {...} ]")

    # normalize IDs
    for i, q in enumerate(data):
        if "id" not in q or not q["id"]:
            q["id"] = f"q{i+1:04d}"
        # 旧データ互換（statementが無い場合）
        if "statement" not in q and "question" in q:
            q["statement"] = q["question"]
        if "explanation" not in q and "rationale" in q:
            q["explanation"] = q["rationale"]

    return data


def load_stats(path: str):
    if not os.path.exists(path):
        return {"wrong_counts": {}, "wrong_stock": [], "updated_at": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = json.load(f)
        if not isinstance(s, dict):
            return {"wrong_counts": {}, "wrong_stock": [], "updated_at": None}
        s.setdefault("wrong_counts", {})
        s.setdefault("wrong_stock", [])
        s.setdefault("updated_at", None)
        return s
    except Exception:
        return {"wrong_counts": {}, "wrong_stock": [], "updated_at": None}


def save_stats(path: str, stats: dict):
    stats["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


# -----------------------------
# Session init
# -----------------------------
def ensure_state():
    if "mode" not in st.session_state:
        st.session_state.mode = "通常モード"
    if "set_ids" not in st.session_state:
        st.session_state.set_ids = []
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    if "submitted" not in st.session_state:
        st.session_state.submitted = False
    if "last_judged" not in st.session_state:
        st.session_state.last_judged = None  # True/False
    if "stats" not in st.session_state:
        st.session_state.stats = load_stats(STATS_PATH)

    # ★① 追加：このセットの正解数
    if "correct_count" not in st.session_state:
        st.session_state.correct_count = 0


def make_new_set(questions, mode: str, set_size: int = SET_SIZE):
    """Pick a new set of question IDs based on mode."""
    all_ids = [q["id"] for q in questions]
    stats = st.session_state.stats
    wrong_stock = list(dict.fromkeys(stats.get("wrong_stock", [])))  # unique keep order

    if mode == "復習モード":
        pool = [qid for qid in wrong_stock if qid in set(all_ids)]
        if not pool:
            st.warning("復習モード：まだ『間違えた問題』がありません。通常モードで解いてください。")
            pool = all_ids
    else:
        pool = all_ids

    if len(pool) <= set_size:
        chosen = pool[:]
        random.shuffle(chosen)
    else:
        chosen = random.sample(pool, set_size)

    st.session_state.set_ids = chosen
    st.session_state.idx = 0
    st.session_state.submitted = False
    st.session_state.last_judged = None

    # ★② 追加：新しいセット開始で正解数リセット
    st.session_state.correct_count = 0


def current_question(questions):
    qmap = {q["id"]: q for q in questions}
    if not st.session_state.set_ids:
        make_new_set(questions, st.session_state.mode, SET_SIZE)
    qid = st.session_state.set_ids[st.session_state.idx]
    return qmap[qid]


def add_to_wrong(qid: str):
    stats = st.session_state.stats
    wc = stats.setdefault("wrong_counts", {})
    wc[qid] = int(wc.get(qid, 0)) + 1

    stock = stats.setdefault("wrong_stock", [])
    if qid not in stock:
        stock.append(qid)

    save_stats(STATS_PATH, stats)


def remove_from_wrong(qid: str):
    """Optionally remove from wrong_stock when answered correctly in review."""
    stats = st.session_state.stats
    stock = stats.setdefault("wrong_stock", [])
    if qid in stock:
        stock.remove(qid)
    save_stats(STATS_PATH, stats)


def reset_wrong_stock():
    stats = st.session_state.stats
    stats["wrong_stock"] = []
    save_stats(STATS_PATH, stats)


def reset_stats_all():
    st.session_state.stats = {"wrong_counts": {}, "wrong_stock": [], "updated_at": None}
    save_stats(STATS_PATH, st.session_state.stats)


def pass_threshold(total: int) -> int:
    """24問=22を基準に、セット数が変わっても近い基準で合格ラインを出す（切り上げ）"""
    if total <= 0:
        return 0
    if total == 24:
        return PASS_LINE_24
    # 22/24 ≒ 0.9167 を切り上げ
    return int((total * PASS_LINE_24 + 24 - 1) // 24)


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Drone Quiz", layout="centered")
ensure_state()

try:
    questions = load_questions(QUESTIONS_PATH)
except Exception as e:
    st.error(str(e))
    st.info("✅ 対応: questions.json を『配列(list)』形式にしてください。例: [ {...}, {...} ]")
    st.stop()

# Sidebar controls
with st.sidebar:
    st.header("設定")

    mode = st.radio(
        "モード",
        ["通常モード", "復習モード"],
        index=0 if st.session_state.mode == "通常モード" else 1,
        help="通常: 全問題からランダム / 復習: 間違えた問題だけ",
    )
    if mode != st.session_state.mode:
        st.session_state.mode = mode
        make_new_set(questions, mode, SET_SIZE)
        rerun()

    st.write(f"1セット: **{SET_SIZE}** 問（ランダム）")
    st.write(f"合格ライン: **{PASS_LINE_24}/{SET_SIZE}**（本番想定）")

    if st.button("🔄 新しい24問セットを作る"):
        make_new_set(questions, st.session_state.mode, SET_SIZE)
        rerun()

    st.divider()
    st.subheader("復習・統計")
    st.caption("※ stats.json に保存（同じPCなら継続します）")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🧹 間違いストックをリセット"):
            reset_wrong_stock()
            if st.session_state.mode == "復習モード":
                make_new_set(questions, st.session_state.mode, SET_SIZE)
            rerun()
    with col_b:
        if st.button("🗑️ 統計を全リセット"):
            reset_stats_all()
            if st.session_state.mode == "復習モード":
                make_new_set(questions, st.session_state.mode, SET_SIZE)
            rerun()

    stats = st.session_state.stats
    wrong_counts = stats.get("wrong_counts", {})
    if wrong_counts:
        st.divider()
        st.subheader("弱点ランキング（間違い回数）")
        items = sorted(wrong_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for rank, (qid, cnt) in enumerate(items, start=1):
            st.write(f"{rank}. **{qid}** — {cnt}回")
    else:
        st.caption("まだ統計がありません（まず解いてみてください）")


# Main
q = current_question(questions)
qid = q["id"]

st.title("一問一答（判定＋解説）")
st.caption(
    f"モード: {st.session_state.mode} ｜ 進捗: {st.session_state.idx + 1}/{len(st.session_state.set_ids)} ｜ "
    f"正解: {st.session_state.correct_count} ｜ ID: {qid}"
)

st.markdown("### 問題")
st.write(q.get("statement", ""))

# Use question-specific widget key
choice_key = f"choice_{qid}"
if choice_key not in st.session_state:
    st.session_state[choice_key] = "正しい"  # default

options = ["正しい", "誤っている"]
disabled = st.session_state.submitted

st.radio(
    "あなたの回答",
    options=options,
    key=choice_key,
    disabled=disabled,
)

col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    if st.button("判定", type="primary", disabled=disabled):
        st.session_state.submitted = True

        user_choice = st.session_state[choice_key]
        correct = (user_choice == q.get("answer"))
        st.session_state.last_judged = correct

        # ★③ 追加：正解なら正解数加算
        if correct:
            st.session_state.correct_count += 1

        if not correct:
            add_to_wrong(qid)
        else:
            if st.session_state.mode == "復習モード":
                remove_from_wrong(qid)

        rerun()

with col2:
    if st.button("リセット", disabled=disabled):
        # ※この形が今の環境で動いている前提（問題が出る場合は「キー削除方式」にします）
        st.session_state[choice_key] = "正しい"
        rerun()

# Result / Explanation
if st.session_state.submitted:
    if st.session_state.last_judged:
        st.success("✅ 正解")
    else:
        st.error("❌ 不正解")

    st.markdown("### 解説（根拠）")
    st.write(q.get("explanation", ""))

    src = q.get("source", {})
    pages = src.get("pages")
    if pages:
        st.caption(f"出典: {src.get('pdf','')} p.{', '.join(map(str, pages))}")

    st.divider()

    # ★④ 追加：セット終了時に合否表示
    is_set_end = (st.session_state.idx >= len(st.session_state.set_ids) - 1)
    if is_set_end:
        total = len(st.session_state.set_ids)
        correct_num = st.session_state.correct_count
        need = pass_threshold(total)
        rate = (correct_num / total * 100) if total else 0.0

        st.subheader("📊 セット結果（合否）")
        st.write(f"正解数：**{correct_num} / {total}**（{rate:.1f}%）")
        st.write(f"合格ライン：**{need} / {total}**")

        if correct_num >= need:
            st.success("🎉 合格ライン達成！")
        else:
            st.error("❌ 不合格（合格ライン未達）")

    next_label = "次の問題へ ▶"
    if is_set_end:
        next_label = "次の24問セットへ ▶"

    if st.button(next_label):
        if is_set_end:
            make_new_set(questions, st.session_state.mode, SET_SIZE)
        else:
            st.session_state.idx += 1

        st.session_state.submitted = False
        st.session_state.last_judged = None
        rerun()
else:
    st.info("回答を選んで **判定** を押してください。")
