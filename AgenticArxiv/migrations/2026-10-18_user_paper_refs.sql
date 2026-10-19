-- 2026-10-18: 账号论文引用表
--
-- 背景：pdf_assets / translate_assets 是按 paper_id 全局唯一的共享缓存。
-- 之前删除操作会直接删掉全局记录和文件，影响所有账号。
-- 现在每个账号登记一条引用，删除只解除自己的引用，最后一个引用消失才删文件。
--
-- 适用：所有现有库（新建库由 init_db/create_all 自动建表，无需执行）

CREATE TABLE IF NOT EXISTS `user_paper_refs` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `paper_id` varchar(128) NOT NULL,
  `kind` varchar(16) NOT NULL DEFAULT 'pdf',
  `created_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_paper_refs_user_paper_kind` (`user_id`,`paper_id`,`kind`),
  KEY `ix_user_paper_refs_paper_kind` (`paper_id`,`kind`),
  CONSTRAINT `fk_user_paper_refs_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 回填：历史会话里出现过的论文，视为该账号引用过该 PDF
INSERT IGNORE INTO `user_paper_refs` (`user_id`, `paper_id`, `kind`, `created_at`)
SELECT `user_id`, `paper_id`, 'pdf', NOW() FROM `session_papers`;

-- 回填：已有译文、且该账号引用过该 PDF 的，补一条 translate 引用
INSERT IGNORE INTO `user_paper_refs` (`user_id`, `paper_id`, `kind`, `created_at`)
SELECT DISTINCT sp.`user_id`, sp.`paper_id`, 'translate', NOW()
FROM `session_papers` sp
JOIN `translate_assets` ta ON ta.`paper_id` = sp.`paper_id`;
