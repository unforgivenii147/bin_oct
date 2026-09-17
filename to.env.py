#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

MODEL_MAPPINGS = {
    "COBUDDY_TOKEN": "baidu/cobuddy:free",
    "CLAUDE_TOKEN": "claude-opus-4-7",
    "DEEPSEEK_CHAT_TOKEN": "deepseek-chat",
    "DEEPSEEK_V4F_TOKEN": "deepseek-v4-flash",
    "DEEPSEEK_V4P_TOKEN": "deepseek-v4-pro",
    "GEMINI_F_TOKEN": "gemini-2.5-flash",
    "GEMINI_LITE_TOKEN": "google/gemini-3.1-flash-lite",
    "GRANITE_TOKEN": "ibm-granite/granite-4.1-8b",
    "LING_TOKEN": "inclusionai/ling-2.6-1t:free",
    "RING_TOKEN": "inclusionai/ring-2.6-1t",
    "RING_FREE_TOKEN": "inclusionai/ring-2.6-1t:free",
    "KIMI_TOKEN": "kimi-k2.5",
    "MISTRAL_M_TOKEN": "mistralai/mistral-medium-3-5",
    "NEMOTRON_TOKEN": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "OPENAI_GPT55_TOKEN": "openai/gpt-5.5",
    "OPENAI_GPT55P_TOKEN": "openai/gpt-5.5-pro",
    "OPENAI_GPT_CHAT_TOKEN": "openai/gpt-chat-latest",
    "OPENROUTER_TOKEN": "openrouter/owl-alpha",
    "PERCEPTRON_TOKEN": "perceptron/perceptron-mk1",
    "LAGUNA_M_TOKEN": "poolside/laguna-m.1:free",
    "LAGUNA_XS_TOKEN": "poolside/laguna-xs.2:free",
    "QWEN35P_TOKEN": "qwen/qwen3.5-plus-20260420",
    "QWEN36_27B_TOKEN": "qwen/qwen3.6-27b",
    "QWEN36_35B_TOKEN": "qwen/qwen3.6-35b-a3b",
    "QWEN36_F_TOKEN": "qwen/qwen3.6-flash",
    "QWEN36_MAX_TOKEN": "qwen/qwen3.6-max-preview",
    "SMART_TOKEN": "smart-chat",
    "TEXT_EMBEDDING_TOKEN": "text-embedding-3-small",
    "GROK_TOKEN": "x-ai/grok-4.3",
}
MODEL_TO_TOKEN_NAME = {v: k for k, v in MODEL_MAPPINGS.items()}


def extract_tokens_with_models(text):
    sections = re.split(r"###\s+", text)
    tokens_with_models = []
    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().split("\n")
        if not lines:
            continue
        first_line = lines[0].strip()
        model_name = re.sub(r"`\d{2}-\d{2} \d{2}:\d{2}`", "", first_line).strip()
        if "|" in model_name:
            model_name = model_name.split("|")[0].strip()
        model_name = model_name.strip("`").strip()
        token_pattern = "sk-[a-zA-Z0-9]+"
        tokens = re.findall(token_pattern, section)
        for token in tokens:
            tokens_with_models.append((model_name if model_name else "unknown", token))
    return tokens_with_models


def get_model_variable_name(model_name):
    if model_name in MODEL_TO_TOKEN_NAME:
        return MODEL_TO_TOKEN_NAME[model_name]
    model_lower = model_name.lower()
    for key, value in MODEL_MAPPINGS.items():
        if value.lower() in model_lower or model_lower in value.lower():
            return key
    safe_name = model_name.upper().replace(" ", "_").replace("-", "_").replace(".", "_")
    safe_name = re.sub(r"[^A-Z0-9_]", "", safe_name)
    return f"{safe_name}_TOKEN"


def save_tokens_to_files(tokens_data):
    if not tokens_data:
        print("No tokens found in README.md")
        return False
    seen = set()
    unique_tokens = []
    for model, token in tokens_data:
        if token not in seen:
            seen.add(token)
            unique_tokens.append((model, token))
    try:
        with open("tokens.txt", "w", encoding="utf-8") as f:
            f.write(f"{'Model':<40} {'Token'}\n")
            f.write("-" * 40 + "\n")
            for model, token in unique_tokens:
                f.write(f"{model[:40]:<40} {token}\n")
        print(f"✅ Saved {len(unique_tokens)} tokens to tokens.txt")
    except Exception as e:
        print(f"❌ Error saving tokens.txt: {e}")
        return False
    try:
        model_tokens = defaultdict(list)
        for model, token in unique_tokens:
            model_tokens[model].append(token)
        env_path = Path.home() / ".env_dynamic"
        with open(env_path, "a", encoding="utf-8") as f:
            for model, tokens in model_tokens.items():
                var_name = get_model_variable_name(model)
                if len(tokens) == 1:
                    f.write(f"{var_name}={tokens[0]}\n")
                else:
                    for i, token in enumerate(tokens, 1):
                        f.write(f"{var_name}_{i}={token}\n")
        print("\n📊 Summary by model:")
        model_counts = defaultdict(int)
        for model, _ in unique_tokens:
            model_counts[model] += 1
        for model, count in sorted(model_counts.items()):
            var_name = get_model_variable_name(model)
            print(f"  • {model} -> {var_name}: {count} token(s)")
        print("\n🔑 First 3 tokens (preview):")
        for i, (model, token) in enumerate(unique_tokens[:3], 1):
            masked = token[:10] + "..." + token[-6:] if len(token) > 16 else token
            var_name = get_model_variable_name(model)
            print(f"  {i}. {var_name}: {masked}")
        if len(unique_tokens) > 3:
            print(f"  ... and {len(unique_tokens) - 3} more")
        return True
    except Exception as e:
        print(f"❌ Error saving .env file: {e}")
        return False


def main():
    input_file = "README.md"
    if not Path(input_file).exists():
        print(f"❌ Error: '{input_file}' not found in the current directory.")
        print(f"Current directory: {Path.cwd()}")
        return False
    try:
        with open(input_file, encoding="utf-8") as f:
            text = f.read()
        print(f"✅ Read {len(text)} characters from {input_file}")
    except Exception as e:
        print(f"❌ Error reading {input_file}: {e}")
        return False
    tokens_data = extract_tokens_with_models(text)
    if not tokens_data:
        print("⚠️  No tokens found in README.md")
        return False
    return save_tokens_to_files(tokens_data)


if __name__ == "__main__":
    print("🚀 Extracting API tokens from README.md...\n")
    success = main()
    if success:
        print("\n✅ Done! Check tokens.txt and .env files.")
    else:
        print("\n❌ Failed to extract tokens.")
