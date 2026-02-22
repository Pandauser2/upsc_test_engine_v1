"""Quick test: check if Anthropic message batches API is enabled."""
import os
import anthropic

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise SystemExit("Set ANTHROPIC_API_KEY in the environment to run this test.")

client = anthropic.Anthropic(api_key=api_key)

message_batch = client.messages.batches.create(
    requests=[
        {
            "custom_id": "first-prompt-in-my-batch",
            "params": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages": [
                    {
                        "role": "user",
                        "content": "Hey Claude, tell me a short fun fact about video games!",
                    }
                ],
            },
        },
        {
            "custom_id": "second-prompt-in-my-batch",
            "params": {
                "model": "claude-sonnet-4-6",
                "max_tokens": 100,
                "messages": [
                    {
                        "role": "user",
                        "content": "Hey Claude, tell me a short fun fact about bees!",
                    }
                ],
            },
        },
    ]
)
print(message_batch)
