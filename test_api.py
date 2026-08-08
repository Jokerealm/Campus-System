import requests
import json

API_KEY = "sk-j1brmAxfUeKjTz3YRV5ejE3rSkbQF0ln"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}

def chat_completion(gateway, messages, model="glm-5.2", headers=HEADERS, **kwargs):
    url = f"{gateway}/v1/chat/completions"
    payload = {"model": model, "messages": messages, **kwargs}
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if response.status_code != 200:
        print("请求失败:", result.get("error", {}).get("message", result))
        return None

    choice = result["choices"][0]
    print("回复:", choice["message"]["content"])
    print("用量:", result["usage"])
    return result


def chat_completion_stream(gateway, messages, model="glm-5.2", headers=HEADERS, **kwargs):
    url = f"{gateway}/v1/chat/completions"
    payload = {"model": model, "messages": messages, "stream": True, **kwargs}
    response = requests.post(url, json=payload, headers=headers, stream=True)

    if response.status_code != 200:
        result = response.json()
        print("请求失败:", result.get("error", {}).get("message", result))
        return

    full_content = ""
    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        choices = chunk.get("choices", [])
        if not choices:
            continue
        content = choices[0].get("delta", {}).get("content", "")
        if content:
            print(content, end="", flush=True)
            full_content += content
    print()
    return full_content


messages = [
    {"role": "system", "content": "你是一个有帮助的AI助手"},
    {"role": "user", "content": "用一句话介绍量子计算"},
]


# ========== 测试 1: aigw.telecomjs.com + openai 格式 ==========
GATEWAY1 = "https://aigw.telecomjs.com"
print("\n" + "=" * 60)
print("测试 1: aigw.telecomjs.com (OpenAI 格式)")
print("=" * 60)

print("\n--- 非流式 ---")
chat_completion(GATEWAY1, messages)

print("\n--- 流式 ---")
chat_completion_stream(GATEWAY1, messages)

# ========== 测试 2: aigw.telecomjs.com + anthropic 格式 ==========
ANTHROPIC_HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
}

print("\n" + "=" * 60)
print("测试 2: aigw.telecomjs.com (Anthropic 格式)")
print("=" * 60)

def anthropic_completion(gateway, messages, model="glm-5.2", max_tokens=100):
    url = f"{gateway}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    response = requests.post(url, json=payload, headers=ANTHROPIC_HEADERS)
    result = response.json()

    if response.status_code != 200:
        print("请求失败:", result.get("error", {}).get("message", result))
        return None

    print("回复:", result.get("content", []))
    print("用量:", result.get("usage", {}))
    return result

anthropic_messages = [
    {"role": "user", "content": "用一句话介绍量子计算"},
]
anthropic_completion(GATEWAY1, anthropic_messages)
