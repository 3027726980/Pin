-- Phase 4.9 补充：用户自定义厂商增加 base_url
-- 添加模型时默认继承厂商 base_url（可在模型配置里修改）

ALTER TABLE user_providers ADD COLUMN base_url VARCHAR(500);

COMMENT ON COLUMN user_providers.base_url IS '厂商默认接口地址（自定义厂商必填，模型配置创建时自动继承，可覆盖）';
