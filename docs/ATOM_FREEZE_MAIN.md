# 原子库分支策略

`main` 暂时冻结原子库产品能力：不注册原子库 HTTP 路由，不执行入库后的原子化 sidecar，不提供原子库前端入口、模型配置或 `pimctl atoms` 命令。已有数据库表、迁移和领域实现保留，便于后续继续维护。

`dev` 保留当前原子库实现与入口，用于后续实验。恢复 `main` 时，将 `backend/app/features.py` 中的 `ATOMS_PRODUCT_ENABLED` 改回 `True`，并重新运行后端与前端检查。
