"""把多账号数据库迁移为单用户结构。

步骤：
1. 建新表（subscriptions / subscription_runs / app_settings）
2. 按 session/paper 去重合并数据
3. 迁移订阅、运行记录、全局配置
4. 删除账号相关表、外键、索引与 user_id 列
5. 把 u<uid>/ 译文目录拉平并更新 DB 路径
"""
import os
import re
import shutil
from datetime import datetime

import pymysql

DB = os.getenv("MIGRATE_DB", "agentic_arxiv")
BASE = os.getenv("MIGRATE_OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "..", "output"))
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

conn = pymysql.connect(host=MYSQL_HOST, user=MYSQL_USER, password=MYSQL_PASSWORD, database=DB, charset="utf8mb4", autocommit=False)
cur = conn.cursor()


def q(sql, args=None):
    cur.execute(sql, args)
    return cur.fetchall()


def x(sql, args=None):
    cur.execute(sql, args)
    return cur.rowcount


def cols(table):
    return [r[0] for r in q("SHOW COLUMNS FROM `%s`" % table)]


print("=== before ===")
for t in ("users", "user_sessions", "user_paper_refs", "sessions", "session_papers",
          "paper_tags", "paper_bookmarks", "translate_assets", "user_subscriptions",
          "user_subscription_runs", "session_papers_backup"):
    try:
        print(t, q(f"SELECT COUNT(*) FROM `{t}`")[0][0], "cols_has_user_id=", "user_id" in cols(t))
    except Exception as e:
        print(t, "ERR", e)

# ---------- 1. 建新表 ----------
import sys
sys.path.insert(0, ".")
from models.db import init_db  # noqa: E402
init_db()
print("created new tables")

# ---------- 2. 去重合并 ----------
# sessions：每个 session_id 保留 last_active/updated 最新的一条
rows = q("SELECT id, session_id, last_active_at, updated_at FROM sessions")
best = {}
for rid, sid, la, up in rows:
    key = (la or up or datetime.min, rid)
    if sid not in best or key > best[sid][0]:
        best[sid] = (key, rid)
keep = [v[1] for v in best.values()]
if keep:
    x("DELETE FROM sessions WHERE id NOT IN (%s)" % ",".join(str(i) for i in keep))
print("sessions kept", len(keep), "of", len(rows))

# session_papers：同一 (session_id, paper_id) 保留最新
rows = q("SELECT id, session_id, paper_id, fetched_at FROM session_papers")
best = {}
for rid, sid, pid, fa in rows:
    key = (fa or datetime.min, rid)
    k = (sid, pid)
    if k not in best or key > best[k][0]:
        best[k] = (key, rid)
keep = [v[1] for v in best.values()]
if keep:
    x("DELETE FROM session_papers WHERE id NOT IN (%s)" % ",".join(str(i) for i in keep))
print("session_papers kept", len(keep), "of", len(rows))

# paper_tags：同一 (paper_id, tag) 保留最早一条
rows = q("SELECT id, paper_id, tag FROM paper_tags ORDER BY id")
seen = {}
for rid, pid, tag in rows:
    seen.setdefault((pid, tag), rid)
keep = list(seen.values())
if keep:
    x("DELETE FROM paper_tags WHERE id NOT IN (%s)" % ",".join(str(i) for i in keep))
print("paper_tags kept", len(keep), "of", len(rows))

# paper_bookmarks：每篇论文保留最新一条
rows = q("SELECT id, paper_id, updated_at FROM paper_bookmarks")
best = {}
for rid, pid, up in rows:
    key = (up or datetime.min, rid)
    if pid not in best or key > best[pid][0]:
        best[pid] = (key, rid)
keep = [v[1] for v in best.values()]
if keep:
    x("DELETE FROM paper_bookmarks WHERE id NOT IN (%s)" % ",".join(str(i) for i in keep))
print("paper_bookmarks kept", len(keep), "of", len(rows))

# translate_assets：每篇论文保留最新一条
rows = q("SELECT id, paper_id, updated_at FROM translate_assets")
best = {}
for rid, pid, up in rows:
    key = (up or datetime.min, rid)
    if pid not in best or key > best[pid][0]:
        best[pid] = (key, rid)
keep = [v[1] for v in best.values()]
if keep:
    x("DELETE FROM translate_assets WHERE id NOT IN (%s)" % ",".join(str(i) for i in keep))
print("translate_assets kept", len(keep), "of", len(rows))

# ---------- 3. 订阅 / 运行记录 / 全局配置 ----------
rows = q("""SELECT sub_id, name, aspects_json, keywords_json, exclude_keywords_json,
                   match_mode, days, max_results, enabled, session_id, interval_minutes,
                   last_run_at, last_run_count, created_at, id
            FROM user_subscriptions""")
best = {}
for r in rows:
    sub_id = r[0]
    key = (r[11] or datetime.min, r[14])
    if sub_id not in best or key > best[sub_id][0]:
        best[sub_id] = (key, r)
for sub_id, (_, r) in best.items():
    x("""INSERT INTO subscriptions
         (sub_id, name, aspects_json, keywords_json, exclude_keywords_json, match_mode,
          days, max_results, enabled, session_id, interval_minutes, last_run_at,
          last_run_count, created_at)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
         ON DUPLICATE KEY UPDATE name=VALUES(name)""",
      (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13]))
print("subscriptions migrated:", sorted(best.keys()))

runs = q("""SELECT sub_id, subscription_name, papers_count, new_papers_count,
                   duration_ms, errors_json, papers_json, run_at FROM user_subscription_runs""")
for r in runs:
    x("""INSERT INTO subscription_runs
         (sub_id, subscription_name, papers_count, new_papers_count, duration_ms,
          errors_json, papers_json, run_at)
         VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", r)
print("runs migrated:", len(runs))

# 全局配置：优先 kongming(27)，否则取最近一个有配置的账号
row = q("""SELECT llm_model, llm_base_url, llm_api_key, translate_service, translate_api_key
           FROM users WHERE id=27""")
src = row[0] if row else None
if src and not any(src):
    row = q("""SELECT llm_model, llm_base_url, llm_api_key, translate_service, translate_api_key
               FROM users WHERE COALESCE(llm_model,'')<>'' OR COALESCE(llm_api_key,'')<>''
                            OR COALESCE(translate_service,'')<>''
               ORDER BY updated_at DESC LIMIT 1""")
    src = row[0] if row else None
if src:
    x("""INSERT INTO app_settings (id, llm_model, llm_base_url, llm_api_key, translate_service, translate_api_key)
         VALUES (1,%s,%s,%s,%s,%s)
         ON DUPLICATE KEY UPDATE llm_model=VALUES(llm_model), llm_base_url=VALUES(llm_base_url),
           llm_api_key=VALUES(llm_api_key), translate_service=VALUES(translate_service),
           translate_api_key=VALUES(translate_api_key)""", src)
print("app_settings seeded:", src is not None)

# ---------- 4. 删除账号结构 ----------
x("SET FOREIGN_KEY_CHECKS=0")
for t, c in q("""SELECT table_name, constraint_name FROM information_schema.referential_constraints
                 WHERE constraint_schema=%s AND referenced_table_name='users'""", (DB,)):
    x(f"ALTER TABLE `{t}` DROP FOREIGN KEY `{c}`")
    print("dropped fk", t, c)

for t in ("sessions", "session_papers", "translate_assets", "translate_tasks",
          "chat_logs", "agent_steps", "paper_comparisons", "comparison_dimensions",
          "paper_annotations", "paper_tags", "paper_bookmarks", "session_papers_backup"):
    if "user_id" not in cols(t):
        continue
    for (idx,) in q("""SELECT DISTINCT index_name FROM information_schema.statistics
                       WHERE table_schema=%s AND table_name=%s AND column_name='user_id'""", (DB, t)):
        try:
            x(f"ALTER TABLE `{t}` DROP INDEX `{idx}`")
        except Exception as e:
            print("drop index failed", t, idx, e)
    x(f"ALTER TABLE `{t}` DROP COLUMN user_id")
    print("dropped user_id from", t)

for t in ("users", "user_sessions", "user_paper_refs", "user_subscriptions", "user_subscription_runs"):
    x(f"DROP TABLE IF EXISTS `{t}`")
    print("dropped table", t)
x("SET FOREIGN_KEY_CHECKS=1")

# 唯一索引
def add_unique(table, name, coldefs):
    try:
        x(f"ALTER TABLE `{table}` ADD UNIQUE KEY `{name}` ({coldefs})")
        print("unique added", table, name)
    except Exception as e:
        print("unique skip", table, name, str(e)[:120])

add_unique("sessions", "uq_sessions_session", "session_id")
add_unique("translate_assets", "uq_translate_assets_paper", "paper_id")
add_unique("paper_tags", "uq_paper_tag", "paper_id, tag")
add_unique("paper_bookmarks", "uq_paper_bookmark", "paper_id")

# ---------- 5. 译文目录拉平 ----------
for base in (os.path.join(BASE, "pdf_translated"), os.path.join(BASE, "pdf_translated_log")):
    if not os.path.isdir(base):
        continue
    for d in sorted(os.listdir(base)):
        p = os.path.join(base, d)
        if not (os.path.isdir(p) and re.fullmatch(r"u\d+", d)):
            continue
        for fn in os.listdir(p):
            src_f = os.path.join(p, fn)
            dst_f = os.path.join(base, fn)
            if os.path.exists(dst_f):
                os.remove(src_f)
            else:
                shutil.move(src_f, dst_f)
        try:
            os.rmdir(p)
        except OSError:
            pass
    print("flattened", base)

rows = q("SELECT id, input_pdf_path, output_mono_path, output_dual_path FROM translate_assets")
for rid, inp, mono, dual in rows:
    def flat(p):
        return re.sub(r"/u\d+/", "/", p) if p else p
    x("UPDATE translate_assets SET input_pdf_path=%s, output_mono_path=%s, output_dual_path=%s WHERE id=%s",
      (flat(inp), flat(mono), flat(dual), rid))
print("updated translate paths:", len(rows))

conn.commit()

print("=== after ===")
for t in ("sessions", "session_papers", "paper_tags", "paper_bookmarks", "translate_assets",
          "subscriptions", "subscription_runs", "app_settings", "users"):
    try:
        print(t, q(f"SELECT COUNT(*) FROM `{t}`")[0][0])
    except Exception as e:
        print(t, "ERR", e)
