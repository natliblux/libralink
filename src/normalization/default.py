import re

def normalize(text: str) -> str:

    text = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', text)
    text = text.replace(" ", "").replace("<", "").replace(">", "")
    text = text.lower()
    return text