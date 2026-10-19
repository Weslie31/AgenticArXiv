-- 2026-10-18: 译文资产按账号隔离
--
-- translate_assets 原来是全局表（paper_id 唯一），译文文件也是全局一份。
-- 现在改为 (user_id, paper_id) 唯一，输出文件放到 pdf_translated/u<user_id>/。
--
-- 现有数据：为每个拥有 translate 引用的账号复制一份记录（仍指向旧的共享文件），
-- 然后删除 user_id=0 的旧行。之后任一账号重翻只会写自己的目录。

ALTER TABLE `translate_assets`
  ADD COLUMN `user_id` bigint NOT NULL DEFAULT 0;

ALTER TABLE `translate_assets`
  DROP INDEX `ix_translate_assets_paper_id`;

ALTER TABLE `translate_assets`
  ADD UNIQUE KEY `uq_translate_assets_user_paper` (`user_id`, `paper_id`),
  ADD KEY `ix_translate_assets_paper_id` (`paper_id`),
  ADD KEY `ix_translate_assets_user_id` (`user_id`);

INSERT INTO `translate_assets`
  (`user_id`, `paper_id`, `input_pdf_path`, `output_mono_path`, `output_dual_path`,
   `status`, `service`, `threads`, `translated_at`, `updated_at`, `error`)
SELECT r.`user_id`, ta.`paper_id`, ta.`input_pdf_path`, ta.`output_mono_path`,
       ta.`output_dual_path`, ta.`status`, ta.`service`, ta.`threads`,
       ta.`translated_at`, ta.`updated_at`, ta.`error`
FROM `translate_assets` ta
JOIN `user_paper_refs` r
  ON r.`paper_id` = ta.`paper_id` AND r.`kind` = 'translate'
WHERE ta.`user_id` = 0;

DELETE FROM `translate_assets` WHERE `user_id` = 0;
