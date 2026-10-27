import re

def normalize(text):
    text = re.sub(r'\[.*?\]|\(.*?\)|\{.*?\}', '', text)
    text = text.replace(" ", "").replace("<", "").replace(">", "")
    text = text.lower()
    if text == "luxembourg":
        text = ""
    return text