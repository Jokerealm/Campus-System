# P3 API 协议文档

本文档维护 P3 `resource-student` 服务的 API 协议。接口字段、状态流和跨团队约定必须与 `system design.docx` 保持一致。

## 基础地址

- 资源服务：`/api/resource/v1`
- 学生服务：`/api/student/v1`
- 健康检查：`/api/health/`
- OpenAPI Schema：`/api/schema/`
- Swagger UI：`/api/docs/`

本地开发地址：

```text
http://127.0.0.1:8103
```

## 请求头

- `X-Teacher-Id`：Mock 教师身份。
- `X-Service-Id`：Mock P1、P2 服务身份。
- `X-Student-Id`：Mock 学生身份。
- 三种 Mock 身份头必须且只能提供一个；后续接入真实鉴权时替换为
  `Authorization: Bearer <token>`。
- Mock 身份和 `X-Tenant-Id` 均由调用方填写，只可用于开发/测试，不能作为生产安全边界。
- 学生请求中的 `student_id` 必须匹配 `X-Student-Id`；教师请求中的
  `reviewer_id`/`created_by` 必须匹配 `X-Teacher-Id`。服务身份可代表教师操作，
  但当前尚缺独立 actor/on-behalf-of 审计字段。
- `X-Request-Id`：可选，请求追踪 ID；不传时服务端自动生成，并透传给 P1。
- `X-Tenant-Id`：可选，学校或租户 ID；不传时使用 `default`。
- `Idempotency-Key`：错题上传和答案提交时可选；相同键只允许重放相同载荷，
  不同载荷返回 `CONFLICT`。并发重放不会重复创建或计分，答案重放返回首次掌握度快照。

## 统一响应格式

所有业务 JSON API 的成功响应和 DRF 异常返回统一外层结构。OpenAPI/Swagger、
未匹配路由以及供 P1 使用的二进制签名文件响应不使用该结构。

成功示例：

```json
{
  "request_id": "req_001",
  "code": "OK",
  "message": "success",
  "data": {}
}
```

失败示例：

```json
{
  "request_id": "req_002",
  "code": "VALIDATION_ERROR",
  "message": "validation error",
  "data": {
    "field": ["field is required"]
  }
}
```

当前实现位置：

- `backend/core/responses.py`：统一成功响应 `api_response()`
- `backend/core/middleware.py`：请求追踪 `RequestIdMiddleware`
- `backend/core/exceptions.py`：统一异常处理 `custom_exception_handler()`

## 错误码

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | `VALIDATION_ERROR` | 请求参数缺失或格式错误。 |
| 401 | `UNAUTHORIZED` | 未登录或认证无效。 |
| 403 | `FORBIDDEN` | 已认证，但无权限访问该资源。 |
| 404 | `NOT_FOUND` | 资源不存在。 |
| 409 | `CONFLICT` | 资源状态冲突，例如重复审核。 |
| 413 | `FILE_TOO_LARGE` | 上传文件超过配置的大小上限。 |
| 415 | `UNSUPPORTED_FILE_TYPE` | 上传文件 MIME 类型不受支持。 |
| 422 | `AI_RESULT_NEEDS_REVIEW` | AI 结果不满足继续学习的前置条件。 |
| 500 | `INTERNAL_ERROR` | 服务内部异常。 |
| 503 | `AI_SERVICE_UNAVAILABLE` | P1 超时、不可用或返回无效响应。 |

## 已实现接口

### 健康检查

`GET /api/health/`

响应 `data`：

```json
{
  "status": "ok"
}
```

状态：已实现。

## 资源服务接口

第一版将知识点、题库、AI 候选和训练包视为全局共享资源；`X-Tenant-Id` 目前只用于
学生记录隔离。若部署为多校共享实例，校本题库、AI 候选和训练包必须先补充资源侧
租户字段与查询约束。

### 获取知识点字典

`GET /api/resource/v1/knowledge-points`

查询参数：

- `subject`：可选，学科，例如 `math`
- `stage`：可选，学段，例如 `junior_middle_school`
- `version`：可选，知识点版本，例如 `2026.1`；不传时默认 `2026.1`
- `enabled`：可选，是否启用

版本语义：`knowledge_point_id` 是稳定业务 ID，同一 ID 可以存在于多个 `version`；跨版本引用时调用方需要同时保留版本上下文。

响应 `data`：

```json
{
  "version": "2026.1",
  "items": [
    {
      "knowledge_point_id": "kp_math_8_function_linear",
      "code": "MATH.8.FUNC.001",
      "name": "一次函数图像与性质",
      "parent_id": "kp_math_8_function",
      "subject": "math",
      "stage": "junior_middle_school",
      "grade_range": ["8"],
      "path": ["数与代数", "函数", "一次函数图像与性质"],
      "version": "2026.1",
      "enabled": true
    }
  ]
}
```

实现位置：

- `backend/resources/models.py`：`KnowledgePoint`
- `backend/resources/serializers.py`：查询参数和返回字段校验
- `backend/resources/views.py`：`KnowledgePointListView`
- `backend/resources/urls.py`：`knowledge-points` 路由

开发库 seed 数据加载：

```bash
docker compose exec -T p3-api python backend/manage.py load_knowledge_points
```

状态：已实现。

### 检索题目

`POST /api/resource/v1/questions/search`

请求：

```json
{
  "knowledge_point_ids": ["kp_math_8_function_linear"],
  "knowledge_point_version": "2026.1",
  "question_type": null,
  "difficulty_range": [0.35, 0.75],
  "source_priority": ["school_bank", "exam_history", "middle_exam_real"],
  "similar_to": {
    "question_html": "<p>如图，在平面直角坐标系中...</p>",
    "exam_question_id": "eq_021_2"
  },
  "limit": 10
}
```

响应 `data`：

```json
{
  "items": [
    {
      "bank_question_id": "bq_001",
      "source": "school_bank",
      "content_html": "<p>已知一次函数 y=2x+1...</p>",
      "answer_html": "<p>...</p>",
      "analysis_html": "<p>...</p>",
      "knowledge_point_ids": ["kp_math_8_function_linear"],
      "knowledge_point_version": "2026.1",
      "question_type": "选择题",
      "difficulty": 0.55,
      "images": [],
      "audit_status": "approved",
      "match_score": 0.91
    }
  ],
  "need_ai_generation": false
}
```

说明：

- `knowledge_point_version`：可选，不传时默认 `2026.1`。
- `source_priority`：可选，只表示来源排序优先级，不作为来源过滤条件；未列出的来源仍可返回，并排在已列出来源之后。
- `similar_to`：第一版仅保留入参，不做真实语义相似检索。
- 只返回 `audit_status=approved` 的题目。
- `need_ai_generation=true` 表示当前题库结果少于 `limit`，后续可触发 P1 生成变式题。

状态：已实现。

### 创建训练包

`POST /api/resource/v1/practice-packs`

请求：

```json
{
  "title": "一次函数薄弱点强化训练",
  "target": "class",
  "target_ref_id": "class_8_3",
  "knowledge_point_ids": ["kp_math_8_function_linear"],
  "knowledge_point_version": "2026.1",
  "question_ids": ["bq_001", "bq_002", "bq_003"],
  "created_by": "teacher_001"
}
```

响应 `data`：

```json
{
  "practice_pack_id": "pack_001",
  "status": "draft"
}
```

说明：

- `target` 当前支持 `class` 和 `student`。
- `knowledge_point_version` 可选，不传时默认 `2026.1`。
- `knowledge_point_ids` 必须能在指定 `knowledge_point_version` 下找到。
- `question_ids` 必须来自同一 `knowledge_point_version` 下已存在且 `audit_status=approved` 的题库题目。
- v1 创建后固定为 `draft`，后续发布、归档和答题记录由学生训练模块继续实现。

状态：已实现。

### 导入题库题目

`POST /api/resource/v1/questions/import`

请求：

```json
{
  "source": "school_bank",
  "knowledge_point_version": "2026.1",
  "items": [
    {
      "bank_question_id": "bq_1001",
      "content_html": "<p>已知一次函数...</p>",
      "answer_html": "<p>...</p>",
      "analysis_html": "<p>...</p>",
      "knowledge_point_ids": ["kp_math_8_function_linear"],
      "question_type": "解答题",
      "difficulty": 0.6,
      "images": [],
      "audit_status": "approved"
    }
  ]
}
```

响应 `data`：

```json
{
  "created_count": 1,
  "updated_count": 0,
  "failed_count": 0,
  "items": [
    {
      "bank_question_id": "bq_1001",
      "status": "created"
    }
  ]
}
```

说明：

- `knowledge_point_version`：可选，不传时默认 `2026.1`。
- `bank_question_id`：可选；不传时服务端生成。传入已有 ID 时会幂等更新该题。
- `knowledge_point_ids` 必须能在指定 `knowledge_point_version` 下找到。
- 第一版导入成功时整体成功；校验失败时返回 `VALIDATION_ERROR`。
- `source=ai_generated` 不能通过通用导入接口写入，必须使用候选保存和审核接口。

开发库 seed 数据加载：

```bash
docker compose exec -T p3-api python backend/manage.py load_question_bank
```

状态：已实现。

### 保存 AI 生成题候选

`POST /api/resource/v1/generated-questions`

请求：

```json
{
  "source_question_id": "bq_001",
  "knowledge_point_version": "2026.1",
  "model_name": "mock-generator",
  "prompt_version": "p1.0",
  "raw_request": {
    "limit": 1
  },
  "items": [
    {
      "generated_question_id": "genq_001",
      "content_html": "<p>已知一次函数...</p>",
      "answer_html": "<p>...</p>",
      "analysis_html": "<p>...</p>",
      "knowledge_point_ids": ["kp_math_8_function_linear"],
      "question_type": "解答题",
      "difficulty": 0.56,
      "images": [],
      "validation": {
        "logic_checked": true,
        "answer_unique": true
      },
      "raw_response": {
        "candidate_index": 0
      }
    }
  ]
}
```

响应 `data`：

```json
{
  "saved_count": 1,
  "created_count": 1,
  "updated_count": 0,
  "audit_status": "pending_review",
  "items": [
    {
      "generated_question_id": "genq_001",
      "status": "created",
      "audit_status": "pending_review"
    }
  ]
}
```

说明：

- `knowledge_point_version`：可选，不传时默认 `2026.1`。
- `generated_question_id`：可选；不传时服务端生成。
- `knowledge_point_ids` 必须能在指定 `knowledge_point_version` 下找到。
- 新保存的候选题固定进入 `pending_review`。
- 已审核过的候选题不能通过该接口覆盖，重复写入会返回 `CONFLICT`。
- 当前接口只保存候选题，不直接调用大模型；后续可由 P1 或独立生成服务调用本接口。

状态：已实现。

### 查询 AI 生成题候选

`GET /api/resource/v1/generated-questions`

查询参数：

- `audit_status`：可选，`pending_review`、`approved` 或 `rejected`
- `knowledge_point_version`：可选，不传时默认 `2026.1`
- `knowledge_point_id`：可选，按知识点过滤
- `limit`：可选，默认 `50`，最大 `100`

响应 `data`：

```json
{
  "items": [
    {
      "generated_question_id": "genq_001",
      "source_question_id": "bq_001",
      "content_html": "<p>已知一次函数...</p>",
      "answer_html": "<p>...</p>",
      "analysis_html": "<p>...</p>",
      "knowledge_point_ids": ["kp_math_8_function_linear"],
      "knowledge_point_version": "2026.1",
      "question_type": "解答题",
      "difficulty": 0.56,
      "images": [],
      "validation": {
        "logic_checked": true
      },
      "audit_status": "pending_review",
      "reviewer_id": null,
      "review_comment": "",
      "reviewed_at": null,
      "model_name": "mock-generator",
      "prompt_version": "p1.0",
      "bank_question_id": null,
      "created_at": "2026-07-04T14:00:00+08:00",
      "updated_at": "2026-07-04T14:00:00+08:00"
    }
  ]
}
```

状态：已实现。

### 获取 AI 生成题候选详情

`GET /api/resource/v1/generated-questions/{generated_question_id}`

响应 `data`：同“查询 AI 生成题候选”中的单个 `item`。

状态：已实现。

### 审核 AI 生成题

`PUT /api/resource/v1/generated-questions/{generated_question_id}/review`

请求：

```json
{
  "decision": "approved",
  "reviewer_id": "teacher_001",
  "review_comment": "通过，可加入校本题库。",
  "publish_to_bank": true
}
```

响应 `data`：

```json
{
  "generated_question_id": "genq_001",
  "audit_status": "approved",
  "bank_question_id": "bq_ai_001"
}
```

说明：

- `decision=approved` 且 `publish_to_bank=true` 时，服务会在同一个事务内创建正式题库题目。
- 发布到题库的题目 `source=ai_generated`，`audit_status=approved`。
- `decision=rejected` 时只更新候选题审核状态，不进入正式题库。
- 已审核过的候选题不能重复审核，重复审核返回 `CONFLICT`。

状态：已实现。

## 学生服务接口

### 上传学生错题

`POST /api/student/v1/wrong-questions`

Content-Type：`multipart/form-data`

表单字段：

- `student_id`：必填，学生 ID
- `subject`：必填，当前为 `math`
- `grade`：必填，年级
- `image`：必填，错题图片

请求必须携带与 `student_id` 一致的 `X-Student-Id`。支持 JPEG、PNG、WebP，
默认最大 10 MiB，同时校验扩展名、声明 MIME 和 PNG/JPEG/WebP 文件头。可使用
`Idempotency-Key` 防止重复上传。

响应 `data`：

```json
{
  "wrong_question_id": "wq_001",
  "recognition_job_id": "job_wrong_001",
  "status": "recognizing"
}
```

状态：已实现。默认调用 Mock P1 并返回 `recognizing`，查询详情时轮询并保存识别结果。
P3 向 P1 提供短时效签名文件 URL，不发送本地磁盘路径；真实 P1 必须能访问
`P1_FILE_BASE_URL`。启动或异步任务失败时进入 `recognition_failed`，使用相同
幂等键和相同载荷可以重试。任务刚提交但尚未返回 `job_id` 时保留短暂宽限期，
避免并发轮询把仍在启动的任务误判为失败。

### 获取错题识别结果

`GET /api/student/v1/wrong-questions/{wrong_question_id}`

响应 `data`：

```json
{
  "wrong_question_id": "wq_001",
  "student_id": "stu_001",
  "status": "recognized",
  "question": {
    "stem_html": "<p>已知一次函数...</p>",
    "question_type": "解答题",
    "images": []
  },
  "knowledge_candidates": [
    {
      "knowledge_point_id": "kp_math_8_function_linear",
      "knowledge_point_name": "一次函数图像与性质",
      "confidence": 0.76
    }
  ],
  "confirmed_knowledge_point_ids": []
}
```

状态：已实现。只允许 `X-Student-Id` 对应学生及同一租户查询，不返回本地文件路径。
`recognition_failed` 时 `recognition_error` 提供可重试的失败摘要。

### 学生确认错题

`PUT /api/student/v1/wrong-questions/{wrong_question_id}/confirm`

请求：

```json
{
  "stem_html": "<p>学生修正后的题干...</p>",
  "knowledge_point_ids": ["kp_math_8_function_linear"]
}
```

响应 `data`：

```json
{
  "wrong_question_id": "wq_001",
  "status": "confirmed"
}
```

状态：已实现。仅允许从 `recognized` 状态确认；重复 PUT 保持幂等，进入学习后禁止逆向修改。
确认知识点必须启用，并与错题的版本、学科和年级兼容。

### 获取引导式讲解下一步

`POST /api/student/v1/wrong-questions/{wrong_question_id}/explanation/next`

请求：

```json
{
  "current_step_index": 1,
  "student_input": "我不会列式",
  "mode": "hint"
}
```

响应 `data`：

```json
{
  "step_index": 2,
  "content": "先找出题目中给出的已知点，再代入 y=kx+b。",
  "next_action": "ask_student",
  "can_show_full_answer": false
}
```

状态：已实现。支持 Mock/HTTP P1 Client，向 P1 透传请求 ID 和租户，记录交互日志，并强制 `can_show_full_answer=false`。
真实 P1 的 `content` 正文仍需在联调阶段增加答案泄漏策略验证。

### 获取学生推荐练习题

`GET /api/student/v1/practice/recommendations`

查询参数：

- `student_id`：必填，学生 ID
- `limit`：可选，默认 `5`

响应 `data`：

```json
{
  "items": [
    {
      "bank_question_id": "bq_001",
      "content_html": "<p>已知一次函数...</p>",
      "knowledge_point_ids": ["kp_math_8_function_linear"],
      "difficulty": 0.55,
      "recommend_reason": "与最近错题属于同一知识点，难度略低。"
    }
  ]
}
```

说明：只返回 `approved` 题目，不返回答案和解析；优先最近错题和低掌握度知识点，
未答题排在已答题前。偏好知识点没有可用题目时回退到同版本其他已审核题目。

状态：已实现。

### 提交练习答案

`POST /api/student/v1/practice/answers`

请求：

```json
{
  "student_id": "stu_001",
  "bank_question_id": "bq_001",
  "answer_text": "y=2x+1",
  "is_correct": true,
  "used_seconds": 180
}
```

响应 `data`：

```json
{
  "answer_record_id": "ans_001",
  "updated_mastery": [
    {
      "knowledge_point_id": "kp_math_8_function_linear",
      "mastery_rate": 0.64
    }
  ]
}
```

说明：支持 `Idempotency-Key`；初始掌握度为 `0.5`，答对 `+0.05`，答错 `-0.08`，
并限制在 `[0.0, 1.0]`。同一请求重放不会重复计分，并返回第一次响应中的掌握度快照。

`is_correct` 来自系统设计文档，当前仅作为可信原型输入使用。学生身份可自行提交该值，
因此生产环境必须改为服务端判题、P1 判题或可信评分服务结果后，才能将掌握度用于正式评价。

状态：已实现。

## 枚举值

题目来源 `source`：

- `school_bank`
- `exam_history`
- `middle_exam_real`
- `external_import`
- `ai_generated`

审核状态 `audit_status`：

- `draft`
- `pending_review`
- `approved`
- `rejected`
- `archived`

AI 生成题候选审核状态 `generated_question.audit_status`：

- `pending_review`
- `approved`
- `rejected`

学生错题状态 `wrong_question.status`：

- `uploaded`
- `recognizing`
- `recognition_failed`
- `recognized`
- `confirmed`
- `learning`
- `mastered`

引导讲解模式 `mode`：

- `hint`
- `check`
- `explain`
- `summary`

训练包目标 `target`：

- `class`
- `student`

## 开发规则

- 新接口实现前或实现时，必须同步更新本文档。
- 成功响应必须使用 `api_response(request, data=...)`。
- 业务状态冲突必须抛出 `ConflictError`。
- AI 生成题必须审核通过后才能进入题库或学生训练。
- 新增字段必须保持向后兼容；删除字段或改变字段含义需要升级 API 版本。
