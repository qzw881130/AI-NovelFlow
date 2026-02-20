-- Migration: Update "电影风格分镜" (System Default) template to match "电影风格分镜 (副本)"
-- Date: 2026-02-20
-- Description: Sync the system default cinema style template with the improved user custom version
--              which includes enhanced "台词零丢失硬约束" (100% dialogue preservation rules)

-- The system default template (电影风格分镜, ID: 3c067438-cb90-43d1-914e-d95c31d1da16)
-- has been updated to match the user custom template (电影风格分镜 (副本), ID: c457795d-08b5-4c4a-8765-2c32d54b080a)

-- Key improvements in the new template:
-- 1. 【台词零丢失硬约束】- Ensures 100% of original dialogue is preserved
-- 2. Quotes extraction step (quotes array) for internal validation
-- 3. Complete self-check mechanism to verify no dialogue is lost
-- 4. Strict speaker mapping rules (no generic terms like "众人/人群")
-- 5. video_description length: 90-220 characters (increased from 90-180)

-- To apply this change manually, run:
UPDATE prompt_templates 
SET template = (SELECT template FROM prompt_templates WHERE id = 'c457795d-08b5-4c4a-8765-2c32d54b080a')
WHERE id = '3c067438-cb90-43d1-914e-d95c31d1da16';
