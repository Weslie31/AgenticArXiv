-- 2026-10-18: 订阅关键词匹配模式
--
-- any = 任一关键词命中（原行为，召回高）
-- all = 所有关键词都要命中（更精确，适合同一主题的多个限定词）

ALTER TABLE `user_subscriptions`
  ADD COLUMN `match_mode` varchar(8) NOT NULL DEFAULT 'any';
