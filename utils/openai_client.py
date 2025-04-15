import openai


def get_openai_response(prompt: str, model: str = "gpt-3.5-turbo"):
    response = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    content = response["choices"][0]["message"]["content"]
    usage = response["usage"]["total_tokens"]
    return {"content": content, "tokens": usage}
