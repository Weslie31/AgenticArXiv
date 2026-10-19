-- 2026-10-17: sessions 表残留的全局唯一索引修复
--
-- 背景：账号体系改造后，sessions 的唯一约束应为 (user_id, session_id)，
-- 但线上库还留着改造前的 UNIQUE(session_id)。这会导致：
--   第一个用户创建 session_id='default' 之后，其他所有用户写同名 session 都会
--   报 Duplicate entry，表现为 Agent 检索后写 session 失败、整轮请求 ERROR。
--
-- ORM（models/orm.py）本身是正确的：session_id 只有普通索引 + 复合唯一索引。
-- 这里把线上库对齐到 ORM 定义。
--
-- 适用场景：2026-10-17 之前创建、且未执行过本脚本的现有库
--   * 从 ORM 新建的空库不需要（create_all 生成的就是普通索引）
--   * 已执行过的库不需要；重复执行只是把该索引删掉再重建，不会丢数据
--
-- 执行前可先检查：non_unique=0 表示仍是唯一索引，需要迁移
SELECT index_name, non_unique
FROM information_schema.statistics
WHERE table_schema = DATABASE()
  AND table_name = 'sessions'
  AND index_name = 'ix_sessions_session_id';

ALTER TABLE sessions DROP INDEX ix_sessions_session_id;
CREATE INDEX ix_sessions_session_id ON sessions (session_id);
