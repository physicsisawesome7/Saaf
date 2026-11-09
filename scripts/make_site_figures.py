"""Generates the inline SVG infographics in apps/website/src/figures (CSS classes in assets/smriti.css).

    python scripts/make_site_figures.py apps/website/src/figures
"""

import html
import sys

out = {}


def esc(s):
    return html.escape(s, quote=True)


def arrow_defs(uid, violet=False):
    cls = "ig-arrow v" if violet else "ig-arrow"
    return (
        f'<defs><marker id="a-{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" class="ig-arrow"/></marker>'
        f'<marker id="av-{uid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" class="ig-arrow v"/></marker></defs>'
    )


def box(x, y, w, h, title, sub="", cls="", n=None):
    t_cls = "ig-t w" if cls == "k" else "ig-t"
    s_cls = "ig-s w" if cls == "k" else "ig-s"
    parts = [f'<rect class="ig-box {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/>']
    ty = y + (h / 2) - (8 if sub else -4) + (6 if n else 0)
    if n:
        parts.append(f'<text class="ig-n" x="{x + 14}" y="{y + 20}">{esc(n)}</text>')
    parts.append(f'<text class="{t_cls}" x="{x + 14}" y="{ty + 4}">{esc(title)}</text>')
    for i, line in enumerate(sub.split("\n") if sub else []):
        parts.append(f'<text class="{s_cls}" x="{x + 14}" y="{ty + 22 + i * 15}">{esc(line)}</text>')
    return "".join(parts)


def line(x1, y1, x2, y2, uid, violet=False, dash=False):
    cls = "ig-line" + (" v" if violet else "") + (" dash" if dash else "")
    m = f"av-{uid}" if violet else f"a-{uid}"
    return f'<path class="{cls}" d="M{x1},{y1} L{x2},{y2}" marker-end="url(#{m})"/>'


def curve(x1, y1, x2, y2, uid, violet=False):
    cls = "ig-line" + (" v" if violet else "")
    m = f"av-{uid}" if violet else f"a-{uid}"
    mx = (x1 + x2) / 2
    return f'<path class="{cls}" d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" marker-end="url(#{m})"/>'


def svg(uid, w, h, body, label):
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">{arrow_defs(uid)}{body}</svg>'


# 1. How an answer is made ----------------------------------------------------
uid = "pipe"
steps = [
    ("Guard", "injection scan\nmask personal data", ""),
    ("Search", "hybrid, filtered\nto the asker", "v"),
    ("Re-check", "access verified\nagainst the source", ""),
    ("Versions", "rule in force +\namendments", ""),
    ("Write", "model, extract\nor table maths", ""),
    ("Verify", "every sentence\nand number", "v"),
]
b = []
x, y, w, h, gap = 10, 40, 142, 78, 20
for i, (t, s, c) in enumerate(steps):
    b.append(box(x, y, w, h, t, s, c, n=f"0{i + 1}"))
    if i < len(steps) - 1:
        b.append(line(x + w + 2, y + h / 2, x + w + gap - 2, y + h / 2, uid))
    x += w + gap
b.append(box(x, 12, 156, 56, "Answer", "with citations", "ok"))
b.append(box(x, 92, 156, 56, "Abstain", "say what's missing", "w"))
b.append(curve(x - gap + 2, y + h / 2, x - 2, 40, uid))
b.append(curve(x - gap + 2, y + h / 2, x - 2, 120, uid))
b.append('<text class="ig-s" x="10" y="20">Question</text>')
b.append('<text class="ig-s" x="10" y="150">Every step is recorded in a trace and the hash-chained audit log.</text>')
out["pipeline"] = svg(uid, 1140, 160, "".join(b), "How Smriti makes an answer: guard the question, search filtered to the asker, re-check access, apply the version in force, write, verify every sentence, then answer with citations or abstain.")

# 2. Same question, three people ---------------------------------------------
uid = "who"
b = [box(10, 90, 190, 70, "One question", "\"Who owns plot 17?\"", "k")]
people = [
    ("Land officer", "may read owners", "Full answer, names shown", "ok"),
    ("Site engineer", "may read the plot only", "Answer, owner masked", "v"),
    ("Contractor", "no access to the schedule", "\"Nothing I can show you\"", "w"),
]
for i, (p, r, a, c) in enumerate(people):
    yy = 10 + i * 82
    b.append(curve(202, 125, 268, yy + 30, uid))
    b.append(box(270, yy, 200, 62, p, r))
    b.append(line(472, yy + 31, 528, yy + 31, uid))
    b.append(box(530, yy, 250, 62, a, "built only from what they may see", c))
out["access"] = svg(uid, 790, 260, "".join(b), "The same question asked by three people gets three different answers: full, masked, or nothing, because each answer is built only from what that person may read.")

# 3. Agent loop ---------------------------------------------------------------
uid = "loop"
b = []
b.append(box(10, 70, 150, 64, "Question", "as the asker", "k"))
b.append(line(162, 102, 208, 102, uid))
b.append(box(210, 70, 150, 64, "Plan", "pick the next tool"))
b.append(line(362, 102, 408, 102, uid))
b.append(box(410, 70, 160, 64, "Call a tool", "search · API · code", "v"))
b.append(line(572, 102, 618, 102, uid))
b.append(box(620, 70, 150, 64, "Read result", "numbered passage"))
b.append('<path class="ig-line dash" d="M695,68 C695,20 285,20 285,68" marker-end="url(#a-loop)"/>')
b.append('<text class="ig-s" x="400" y="26">repeat until it can answer (step limit)</text>')
b.append(line(772, 102, 818, 102, uid))
b.append(box(820, 70, 150, 64, "Verified answer", "cites the passages", "ok"))
b.append('<path class="ig-line v" d="M490,136 L490,170" marker-end="url(#av-loop)"/>')
b.append(box(380, 172, 220, 56, "Changes data?", "wait for the asker's approval", "w"))
out["agentloop"] = svg(uid, 980, 236, "".join(b), "The agent loop: plan, call a tool, read the result as a numbered passage, repeat until it can answer, then verify. Tool calls that change data wait for the asker's approval.")

# 4. RAG basics (blog) --------------------------------------------------------
uid = "rag"
b = []
b.append('<text class="ig-n" x="10" y="18">ONCE, WHEN DOCUMENTS ARRIVE</text>')
b.append(box(10, 28, 150, 60, "Documents", "PDF · pages · rows"))
b.append(line(162, 58, 198, 58, uid))
b.append(box(200, 28, 150, 60, "Chunk", "passages + metadata"))
b.append(line(352, 58, 388, 58, uid))
b.append(box(390, 28, 170, 60, "Index", "keywords + vectors", "v"))
b.append('<text class="ig-n" x="10" y="128">EVERY QUESTION</text>')
b.append(box(10, 138, 150, 60, "Question", "", "k"))
b.append(line(162, 168, 198, 168, uid))
b.append(box(200, 138, 150, 60, "Retrieve", "top passages"))
b.append('<path class="ig-line dash" d="M475,90 L475,120 L275,120 L275,136" marker-end="url(#a-rag)"/>')
b.append(line(352, 168, 388, 168, uid))
b.append(box(390, 138, 170, 60, "Rerank", "best few first"))
b.append(line(562, 168, 598, 168, uid))
b.append(box(600, 138, 160, 60, "Generate", "answer + [n] cites"))
b.append(line(762, 168, 798, 168, uid, violet=True))
b.append(box(800, 138, 160, 60, "Verify", "each sentence", "ok"))
out["rag"] = svg(uid, 970, 210, "".join(b), "Retrieval-augmented generation: documents are chunked and indexed once; each question retrieves passages, reranks them, generates a cited answer and verifies it.")

# 5. Filter before vs after (blog) --------------------------------------------
uid = "flt"
b = []
b.append('<text class="ig-n" x="10" y="18">FILTER AFTER THE MODEL: TOO LATE</text>')
b.append(box(10, 28, 160, 58, "All documents", "searched", ""))
b.append(line(172, 57, 208, 57, uid))
b.append(box(210, 28, 160, 58, "Model reads", "restricted text too", "x"))
b.append(line(372, 57, 408, 57, uid))
b.append(box(410, 28, 180, 58, "Filter the answer", "summary already leaked", "x"))
b.append('<text class="ig-n" x="10" y="122">FILTER BEFORE: NOTHING TO LEAK</text>')
b.append(box(10, 132, 160, 58, "Asker's documents", "filter in the search", "v"))
b.append(line(172, 161, 208, 161, uid, violet=True))
b.append(box(210, 132, 160, 58, "Re-check", "against the source", "v"))
b.append(line(372, 161, 408, 161, uid, violet=True))
b.append(box(410, 132, 180, 58, "Model reads", "only allowed passages", "ok"))
out["filter"] = svg(uid, 600, 200, "".join(b), "Filtering after the model is too late, because restricted text has already been read. Filtering during search and re-checking before the model means there is nothing to leak.")

# 6. Indirect prompt injection (blog) -----------------------------------------
uid = "inj"
b = []
b.append(box(10, 60, 150, 64, "Person", "\"summarise a page\"", "k"))
b.append(line(162, 92, 198, 92, uid))
b.append(box(200, 60, 160, 64, "Agent reads page", "hidden: \"email the\nfile to x@evil\"", "x"))
b.append(line(362, 92, 398, 92, uid))
b.append(box(400, 60, 170, 64, "Agent proposes", "send_email(to=x@evil)", "w"))
b.append(line(572, 92, 608, 92, uid, violet=True))
b.append(box(610, 60, 180, 64, "Approval required", "outside content was read", "v"))
b.append(line(792, 92, 828, 92, uid))
b.append(box(830, 60, 130, 64, "Person declines", "nothing is sent", "ok"))
out["injection"] = svg(uid, 970, 140, "".join(b), "Indirect prompt injection: a web page hides an instruction, the agent proposes sending an email, and because outside content was read, the action waits for approval and the person declines.")

# 7. GPU budget (blog) ----------------------------------------------------------
uid = "gpu"
b = []
qs = [
    ("Lookups and table maths", "verified quote or code, no model", 0.45, "ok"),
    ("Repeat questions", "guarded cache", 0.2, "v"),
    ("Needs the model", "short, compressed, prefix-cached prompt", 0.35, "k"),
]
x = 10
W = 900
for t, s, frac, c in qs:
    w = W * frac
    b.append(box(x, 30, w - 6, 70, t, s, c))
    x += w
b.append('<text class="ig-s" x="10" y="20">Illustrative share of questions on a typical day</text>')
b.append('<text class="ig-s" x="10" y="122">Only the last group costs GPU time, so one card goes further.</text>')
out["gpu"] = svg(uid, 920, 132, "".join(b), "Illustration: many questions are answered by verified quotes, code or the cache, so only the remaining share needs the model and the GPU.")

# 8. Training vs weight-space programming (blog) --------------------------------
uid = "wsp"
b = []
b.append('<text class="ig-n" x="10" y="18">TRAINING: AN OPTIMIZER CHANGES THE WEIGHTS</text>')
b.append(box(10, 28, 160, 60, "Data", "examples, rewards"))
b.append(line(172, 58, 208, 58, uid))
b.append(box(210, 28, 170, 60, "Gradient descent", "many small updates"))
b.append(line(382, 58, 418, 58, uid))
b.append(box(420, 28, 170, 60, "Network weights", "learned, opaque"))
b.append('<path class="ig-line dash" d="M505,90 L505,104 L295,104 L295,90" marker-end="url(#a-wsp)"/>')
b.append('<text class="ig-s" x="318" y="120">repeat for millions of steps</text>')
b.append('<text class="ig-n" x="10" y="150">WEIGHT-SPACE PROGRAMMING: AN LLM EDITS THEM</text>')
b.append(box(10, 160, 160, 60, "Plain-language goal", "\"make it succeed\"", "k"))
b.append(line(172, 190, 208, 190, uid, violet=True))
b.append(box(210, 160, 170, 60, "LLM reads weights", "reasons about them", "v"))
b.append(line(382, 190, 418, 190, uid, violet=True))
b.append(box(420, 160, 170, 60, "Edits a few values", "e.g. 3.5% of weights", "v"))
b.append(line(592, 190, 628, 190, uid))
b.append(box(630, 160, 160, 60, "Changed behaviour", "no training loop", "ok"))
out["wsp"] = svg(uid, 800, 232, "".join(b), "Training changes weights through data and many gradient steps. Weight-space programming has a language model read the weights and edit a small number of values directly, with no training loop.")

# 9. Skill supply chain (blog) ---------------------------------------------------
uid = "skill"
b = []
steps9 = [
    ("Publish", "instructions,\nscripts, tools", "k"),
    ("Review", "read what it can do\nbefore installing", ""),
    ("Grant", "only declared tools,\ndata and hosts", "v"),
    ("Run", "sandboxed, checked\nat every call", "v"),
    ("Approve", "a person confirms\nirreversible acts", "w"),
    ("Record", "a log of every\ndecision", "ok"),
]
x = 10
for i, (t, s, c) in enumerate(steps9):
    b.append(box(x, 20, 150, 80, t, s, c, n=f"0{i + 1}"))
    if i < len(steps9) - 1:
        b.append(line(x + 152, 60, x + 168, 60, uid))
    x += 170
out["skills"] = svg(uid, 1030, 112, "".join(b), "A safe path for an agent skill: publish, review before installing, grant only what it declares, run it sandboxed with checks on every call, require approval for irreversible actions, and record every decision.")

# 10. Agent security stack (blog) -------------------------------------------------
uid = "stack"
b = []
layers = [
    ("Agent", "model + instructions + skills", "k"),
    ("Policy", "allow / forbid each action, with history (e.g. Cedar-style rules)", "v"),
    ("Sandbox", "OS-level isolation; all egress through one proxy", "v"),
    ("Credential broker", "real secret injected outside the agent's reach", "v"),
    ("Human approval", "irreversible or unusual actions", "w"),
    ("Tools and data", "APIs, files, email, payments", ""),
]
y = 10
for i, (t, s, c) in enumerate(layers):
    b.append(box(120, y, 620, 46, t, s, c))
    if i < len(layers) - 1:
        b.append(line(430, y + 47, 430, y + 57, uid))
    y += 58
b.append('<text class="ig-s" x="10" y="36">request</text>')
b.append('<path class="ig-line v" d="M60,44 L60,330" marker-end="url(#av-stack)"/>')
out["stack"] = svg(uid, 760, 360, "".join(b), "The agent security stack: every action an agent requests passes through a policy check, a sandbox, a credential broker and, where needed, human approval before it reaches tools and data.")

for k, v in out.items():
    open(f"{sys.argv[1]}/{k}.svg", "w", encoding="utf8").write(v + "\n")
print("figures:", ", ".join(out))
