-- =========================================================
-- 账号系统迁移（含 user_id 隔离、按账号独立订阅）
-- 执行前请确认 USE agentic_arxiv; 命中的是目标库
-- 整个脚本可重入：DROP/CREATE 都做了 IF EXISTS 判断；
-- 但 UPDATE 阶段会把所有 user_id IS NULL 归到占位账号(1)，
-- 重跑会让已有"真实账号数据"被改写到占位账号——请只在首次迁移执行。
-- =========================================================

USE agentic_arxiv;

-- =========================================================
-- 1. 账号表 + 会话表
-- =========================================================

-- =========================================================
-- 1. 账号表（每个账号独立接入模型配置）
--    - llm_model / llm_base_url / llm_api_key 为 NULL 时，
--      回退到系统环境变量 / config.py 默认值
--    - 已有库：可重入，列已存在则忽略
-- =========================================================
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    username        VARCHAR(64) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(128) NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    is_admin        TINYINT(1) NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at   DATETIME NULL,
    -- ----- 每个账号独立的接入模型配置（可空，回退系统默认） -----
    llm_model       VARCHAR(128) NULL,
    llm_base_url    VARCHAR(512) NULL,
    llm_api_key     VARCHAR(255) NULL,
    UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 兼容已存在但缺字段的库（已存在则忽略，MySQL 8 支持 IF NOT EXISTS）
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS llm_model    VARCHAR(128) NULL,
    ADD COLUMN IF NOT EXISTS llm_base_url VARCHAR(512) NULL,
    ADD COLUMN IF NOT EXISTS llm_api_key  VARCHAR(255) NULL;

CREATE TABLE IF NOT EXISTS user_sessions (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT NOT NULL,
    token           VARCHAR(128) NOT NULL,
    expires_at      DATETIME NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_sessions_token (token),
    KEY ix_user_sessions_user_id (user_id),
    KEY ix_user_sessions_expires (expires_at),
    CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =========================================================
-- 2. 占位账号：承接迁移前的所有历史数据
--    真实账号从 id=2 开始注册
-- =========================================================
INSERT INTO users (id, username, password_hash, display_name, is_active, is_admin)
VALUES (1, '_legacy_placeholder', '!NO_LOGIN!', 'Legacy Data', 0, 1)
ON DUPLICATE KEY UPDATE id = id;

-- =========================================================
-- 3. 给所有"按账号隔离"业务表加 user_id 列（先 NULL，迁完数据再 NOT NULL）
-- =========================================================
ALTER TABLE sessions              ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE session_papers        ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE translate_tasks       ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE chat_logs             ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE agent_steps           ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE paper_annotations     ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE paper_tags            ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE paper_bookmarks       ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE paper_comparisons     ADD COLUMN user_id BIGINT NULL AFTER id;
ALTER TABLE comparison_dimensions ADD COLUMN user_id BIGINT NULL AFTER id;

-- =========================================================
-- 4. 索引（加速按用户过滤）
-- =========================================================
CREATE INDEX ix_sessions_user_id              ON sessions(user_id);
CREATE INDEX ix_session_papers_user_id        ON session_papers(user_id);
CREATE INDEX ix_translate_tasks_user_id       ON translate_tasks(user_id);
CREATE INDEX ix_chat_logs_user_id             ON chat_logs(user_id);
CREATE INDEX ix_agent_steps_user_id           ON agent_steps(user_id);
CREATE INDEX ix_paper_annotations_user_id     ON paper_annotations(user_id);
CREATE INDEX ix_paper_tags_user_id            ON paper_tags(user_id);
CREATE INDEX ix_paper_bookmarks_user_id       ON paper_bookmarks(user_id);
CREATE INDEX ix_paper_comparisons_user_id     ON paper_comparisons(user_id);
CREATE INDEX ix_comparison_dimensions_user_id ON comparison_dimensions(user_id);

-- =========================================================
-- 5. 调整 unique 约束：让每个账号独立拥有同名 session / 独立收藏
--    出现 "check that column/key exists" 报错时，SHOW INDEX FROM <table>;
--    把索引名替换成你实际的名字（脚本里列的是常见名）
-- =========================================================
-- 5a. sessions: session_id 原本全局唯一 → 改为 (user_id, session_id) 联合唯一
--     如果你的原索引名不是 session_id，先 SHOW INDEX FROM sessions 查实际名
ALTER TABLE sessions DROP INDEX session_id;
ALTER TABLE sessions ADD CONSTRAINT uq_sessions_user_session UNIQUE (user_id, session_id);

-- 5b. paper_tags: 原本 (paper_id, tag) → 改为 (user_id, paper_id, tag)
ALTER TABLE paper_tags DROP INDEX uq_paper_tag;
ALTER TABLE paper_tags ADD CONSTRAINT uq_paper_tags_user_paper_tag UNIQUE (user_id, paper_id, tag);

-- 5c. paper_bookmarks: paper_id 全局唯一 → 改为 (user_id, paper_id)
--     如果报错说索引不存在，先 SHOW INDEX FROM paper_bookmarks; 找到 paper_id 的 unique 索引名替换
ALTER TABLE paper_bookmarks DROP INDEX uq_paper_bookmark;
ALTER TABLE paper_bookmarks ADD CONSTRAINT uq_paper_bookmarks_user_paper UNIQUE (user_id, paper_id);

-- 5d. paper_comparisons.comparison_id 仍保留全局唯一（前端跳转 URL 用到）

-- =========================================================
-- 6. 已有 NULL 数据归到占位账号 (id=1)
-- =========================================================
UPDATE sessions              SET user_id = 1 WHERE user_id IS NULL;
UPDATE session_papers        SET user_id = 1 WHERE user_id IS NULL;
UPDATE translate_tasks       SET user_id = 1 WHERE user_id IS NULL;
UPDATE chat_logs             SET user_id = 1 WHERE user_id IS NULL;
UPDATE agent_steps           SET user_id = 1 WHERE user_id IS NULL;
UPDATE paper_annotations     SET user_id = 1 WHERE user_id IS NULL;
UPDATE paper_tags            SET user_id = 1 WHERE user_id IS NULL;
UPDATE paper_bookmarks       SET user_id = 1 WHERE user_id IS NULL;
UPDATE paper_comparisons     SET user_id = 1 WHERE user_id IS NULL;
UPDATE comparison_dimensions SET user_id = 1 WHERE user_id IS NULL;

-- =========================================================
-- 7. 收紧约束：user_id 改为 NOT NULL
--    上面 UPDATE 之后还残留 NULL，这一步会失败提示重跑第 6 步
-- =========================================================
ALTER TABLE sessions              MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE session_papers        MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE translate_tasks       MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE chat_logs             MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE agent_steps           MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE paper_annotations     MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE paper_tags            MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE paper_bookmarks       MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE paper_comparisons     MODIFY COLUMN user_id BIGINT NOT NULL;
ALTER TABLE comparison_dimensions MODIFY COLUMN user_id BIGINT NOT NULL;

-- =========================================================
-- 8. 加外键
-- =========================================================
ALTER TABLE sessions              ADD CONSTRAINT fk_sessions_user              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE session_papers        ADD CONSTRAINT fk_session_papers_user        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE translate_tasks       ADD CONSTRAINT fk_translate_tasks_user       FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE chat_logs             ADD CONSTRAINT fk_chat_logs_user             FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE agent_steps           ADD CONSTRAINT fk_agent_steps_user           FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE paper_annotations     ADD CONSTRAINT fk_paper_annotations_user     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE paper_tags            ADD CONSTRAINT fk_paper_tags_user            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE paper_bookmarks       ADD CONSTRAINT fk_paper_bookmarks_user       FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE paper_comparisons     ADD CONSTRAINT fk_paper_comparisons_user     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE comparison_dimensions ADD CONSTRAINT fk_comparison_dimensions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- =========================================================
-- 9. 用户级订阅持久化表（让多账号各自维护自己的订阅 + 执行历史）
--    设计要点：
--    - (user_id, sub_id) 联合唯一：每个账号可以用同名 sub_id（如 daily_user）
--    - 预置 4 个默认订阅（每个账号首次访问时插入）；用 INSERT IGNORE + 触发器
--      在用户首次创建账号时种入太复杂，这里用应用层在用户首登时检查并补齐
-- =========================================================
CREATE TABLE IF NOT EXISTS user_subscriptions (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT NOT NULL,
    sub_id          VARCHAR(128) NOT NULL,
    name            VARCHAR(128) NOT NULL,
    aspects_json    TEXT NOT NULL DEFAULT '[]',
    keywords_json   TEXT NOT NULL DEFAULT '[]',
    exclude_keywords_json TEXT NOT NULL DEFAULT '[]',
    days            INT NOT NULL DEFAULT 7,
    max_results     INT NOT NULL DEFAULT 15,
    enabled         TINYINT(1) NOT NULL DEFAULT 1,
    session_id      VARCHAR(128) NOT NULL DEFAULT 'default',
    interval_minutes INT NULL,
    last_run_at     DATETIME NULL,
    last_run_count  INT NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_subscriptions_user_sub (user_id, sub_id),
    KEY ix_user_subscriptions_user_id (user_id),
    CONSTRAINT fk_user_subscriptions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_subscription_runs (
    id                  BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id             BIGINT NOT NULL,
    sub_id              VARCHAR(128) NOT NULL,
    subscription_name   VARCHAR(128) NOT NULL DEFAULT '',
    papers_count        INT NOT NULL DEFAULT 0,
    new_papers_count    INT NOT NULL DEFAULT 0,
    duration_ms         INT NOT NULL DEFAULT 0,
    errors_json         TEXT NOT NULL DEFAULT '[]',
    papers_json         TEXT NOT NULL DEFAULT '[]',
    run_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_user_sub_runs_user_id (user_id),
    KEY ix_user_sub_runs_sub_id (sub_id),
    KEY ix_user_sub_runs_run_at (run_at),
    CONSTRAINT fk_user_sub_runs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =========================================================
-- 10. 给所有用户（包括占位）补齐 4 个默认订阅
--     占位账号 id=1 的订阅仍然可见但不触发（因为它不可登录）
-- =========================================================
INSERT IGNORE INTO user_subscriptions
    (user_id, sub_id, name, aspects_json, keywords_json, exclude_keywords_json,
     days, max_results, enabled, session_id, interval_minutes)
SELECT u.id, 'daily_ml', '机器学习每日精选',
       '["LG"]',
       '["neural","deep learning","transformer","LLM","diffusion","generative"]',
       '["survey","review"]', 3, 20, 1, 'default', 1440
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM user_subscriptions us
    WHERE us.user_id = u.id AND us.sub_id = 'daily_ml'
);

INSERT IGNORE INTO user_subscriptions
    (user_id, sub_id, name, aspects_json, keywords_json, exclude_keywords_json,
     days, max_results, enabled, session_id, interval_minutes)
SELECT u.id, 'daily_cv', '计算机视觉每日精选',
       '["CV"]',
       '["image","video","object detection","segmentation","diffusion model"]',
       '["survey","review"]', 3, 15, 1, 'default', 1440
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM user_subscriptions us
    WHERE us.user_id = u.id AND us.sub_id = 'daily_cv'
);

INSERT IGNORE INTO user_subscriptions
    (user_id, sub_id, name, aspects_json, keywords_json, exclude_keywords_json,
     days, max_results, enabled, session_id, interval_minutes)
SELECT u.id, 'daily_nlp', '自然语言处理每日精选',
       '["CL"]',
       '["language model","LLM","transformer","text","dialogue","reasoning"]',
       '[]', 3, 15, 1, 'default', 1440
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM user_subscriptions us
    WHERE us.user_id = u.id AND us.sub_id = 'daily_nlp'
);

INSERT IGNORE INTO user_subscriptions
    (user_id, sub_id, name, aspects_json, keywords_json, exclude_keywords_json,
     days, max_results, enabled, session_id, interval_minutes)
SELECT u.id, 'daily_ai', '人工智能综合',
       '["AI"]',
       '["reinforcement learning","robotics","planning","knowledge"]',
       '[]', 5, 10, 1, 'default', 1440
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM user_subscriptions us
    WHERE us.user_id = u.id AND us.sub_id = 'daily_ai'
);

-- =========================================================
-- 11. 把占位账号的 user_subscriptions 全部设为 disabled
--     避免占位账号的"默认订阅"被调度器误触发
-- =========================================================
UPDATE user_subscriptions SET enabled = 0 WHERE user_id = 1;

-- =========================================================
-- 12. 安全提示
-- =========================================================
SELECT '账号系统迁移完成。请重启后端让 ORM 注册新表结构。' AS message;
SELECT COUNT(*) AS total_users FROM users;
SELECT COUNT(*) AS total_subscriptions FROM user_subscriptions;
