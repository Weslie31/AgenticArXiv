-- 订阅/运行记录缺少指向 users 的外键，删除账号后会留下孤儿订阅，
-- 调度器还会继续为不存在的账号排任务。先清理孤儿行，再补级联外键。

DELETE FROM user_subscription_runs
WHERE user_id NOT IN (SELECT id FROM users);

DELETE FROM user_subscriptions
WHERE user_id NOT IN (SELECT id FROM users);

ALTER TABLE user_subscriptions
  ADD CONSTRAINT fk_user_subscriptions_user
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

ALTER TABLE user_subscription_runs
  ADD CONSTRAINT fk_user_sub_runs_user
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
