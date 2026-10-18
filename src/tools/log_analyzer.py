
def analyze_logs(log_text):
    print(log_text)
    if not log_text.strip():
        return {
            "status": "error", 
            "summary": "No log text provided.", 
            "line_count": 0, 
            "errors": ["Log text is empty."]
        }

    return {
        "status": "success", 
        "summary": "Log analysis completed successfully.", 
        "line_count": len(log_text.splitlines()), 
        "errors": []
    }

print(analyze_logs(input("Give Log: ")))