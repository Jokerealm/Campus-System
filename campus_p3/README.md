# P3 题库与学生训练服务

P3 是校园考试诊断与错题强化系统中的资源和学生学习服务，提供知识点字典、题库检索、训练包、AI 生成题审核、学生错题、引导讲解、推荐练习和掌握度更新。

## 本地启动

要求：Docker Desktop 和 Docker Compose。

```bash
cp .env.example .env
# 运行 `openssl rand -hex 32`，将输出填入 .env 的 DJANGO_SECRET_KEY。
docker compose up --build -d
docker compose exec p3-api python backend/manage.py migrate
docker compose exec p3-api python backend/manage.py load_knowledge_points
docker compose exec p3-api python backend/manage.py load_question_bank
```

启动后可访问：

- 健康检查：`http://127.0.0.1:8103/api/health/`
- Swagger UI：`http://127.0.0.1:8103/api/docs/`
- OpenAPI Schema：`http://127.0.0.1:8103/api/schema/`

学生错题图片保存在 Docker 命名卷 `p3_media` 中，不会提交到 git。
签名文件 URL 依赖 `DJANGO_SECRET_KEY`；Compose 会拒绝空值，请勿使用示例值或
将真实密钥提交到仓库。

## Mock 身份（仅开发/测试）

开发阶段每个业务请求必须且只能携带一个身份头：

- 教师：`X-Teacher-Id: teacher_001`
- P1/P2 服务：`X-Service-Id: p2-service`
- 学生：`X-Student-Id: stu_001`

`X-Tenant-Id` 可选，默认是 `default`。学生请求里的 `student_id` 必须与
`X-Student-Id` 一致；教师请求里的 `reviewer_id`、`created_by` 必须与
`X-Teacher-Id` 一致。服务身份可代表教师发起资源操作，当前尚未记录独立的
`actor_service_id + on_behalf_of_teacher_id`，不能作为生产审计依据。

Mock 请求头可由客户端自行填写，不能用于生产鉴权。当前只有学生数据按
`tenant_id + student_id` 隔离；知识点、题库、AI 候选和训练包仍按全局资源处理，
校本资源的多租户隔离见 `plan.md`。

## P1 模式

默认 `P1_CLIENT_MODE=mock`，无需运行 P1 即可完成错题识别和引导讲解流程。
Docker Compose 会读取 `.env` 中的 P1 配置。P1 运行在宿主机时可使用：

```dotenv
P1_CLIENT_MODE=http
P1_BASE_URL=http://host.docker.internal:8101/api/ai/v1
P1_TIMEOUT_SECONDS=10
P1_SERVICE_ID=p3-service
P1_AUTH_TOKEN=
P1_FILE_BASE_URL=http://127.0.0.1:8103
P1_FILE_URL_TTL_SECONDS=3600
P1_RECOGNITION_START_GRACE_SECONDS=30
```

若 P1 与 P3 位于同一 Compose 网络，将 `P1_BASE_URL` 改为 P1 服务名，
并将 `P1_FILE_BASE_URL` 设为 `http://p3-api:8103`。非 Docker 本地运行时，
两者可使用 `localhost`。`P1_FILE_BASE_URL` 留空则根据学生请求中的 P3 地址生成。

P3 会向 P1 透传 `X-Request-Id`、`X-Tenant-Id`，并携带服务身份；配置真实令牌后
使用 Bearer 认证。错题文件通过默认一小时有效的签名 URL 提供给异步 P1，URL
不会暴露本地路径。网络、超时及无效响应统一映射为
`AI_SERVICE_UNAVAILABLE`，失败记录进入 `recognition_failed`，以相同
`Idempotency-Key` 和相同载荷可重试。

## 主要接口

资源接口使用 `/api/resource/v1`：

- `GET /knowledge-points`
- `POST /questions/import`
- `POST /questions/search`
- `POST /practice-packs`
- `GET|POST /generated-questions`
- `PUT /generated-questions/{id}/review`

学生接口使用 `/api/student/v1`：

- `POST /wrong-questions`
- `GET /wrong-questions/{id}`
- `PUT /wrong-questions/{id}/confirm`
- `POST /wrong-questions/{id}/explanation/next`
- `GET /practice/recommendations`
- `POST /practice/answers`

错题上传和答案提交支持 `Idempotency-Key`；相同键只能重放相同载荷，否则返回
`CONFLICT`。完整字段和响应示例见 [API_PROTOCOL.md](API_PROTOCOL.md)。

训练包目前只实现草稿创建，尚无列表、发布、分发、学生领取和完成进度接口。

## 测试

```bash
docker compose exec p3-api python backend/manage.py test
docker compose exec p3-api python backend/manage.py spectacular --validate --file /tmp/p3-openapi.yaml
```

测试覆盖资源身份和权限、知识点、题库导入和检索、训练包、AI 题审核、错题状态流转、学生数据隔离、签名文件下载、P1 Mock/HTTP 契约、引导讲解、推荐练习、答题幂等和掌握度上下限。
