import anthropic
import subprocess
import os

# Read the diff
with open("pr_diff.txt", "r") as f:
    diff = f.read()

if not diff.strip():
    print("No changes to review.")
    exit(0)

# Truncate if too large (API limit safety)
MAX_CHARS = 15000
if len(diff) > MAX_CHARS:
    diff = diff[:MAX_CHARS] + "\n\n[...diff truncated for length...]"

# Call Claude API
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1500,
    messages=[
        {
            "role": "user",
            "content": f"""You are an expert code reviewer. Review the following PR diff and provide feedback on:

1. **Bugs or logic errors**
2. **Security vulnerabilities**
3. **Performance issues**
4. **Code quality & best practices**
5. **Missing error handling**

Be concise and actionable. Use bullet points. If the code looks good, say so briefly.

````diff
{diff}
```"""
        }
    ]
)

review_comment = message.content[0].text

# Post comment to GitHub PR via CLI
comment_body = f"## 🤖 Claude Code Review\n\n{review_comment}\n\n---\n*Automated review by Claude*"

subprocess.run([
    "gh", "pr", "comment", os.environ["PR_NUMBER"],
    "--repo", os.environ["REPO"],
    "--body", comment_body
], check=True)

print("Review posted successfully.")
```

---

### **Step 4 — Commit and Push**

```bash
git add .github/workflows/claude-code-review.yml
git add .github/scripts/claude_review.py
git commit -m "Add Claude automated code review"
git push
```

---

### **Step 5 — Test It**

Create a new PR — Claude will automatically comment with a review within ~30 seconds.

---

## Optional Enhancements

| Feature | How |
|---|---|
| **Review only specific file types** | Filter diff by `.py`, `.js`, `.java` etc. before sending |
| **Severity labels** | Prompt Claude to tag issues as `[HIGH]`, `[MEDIUM]`, `[LOW]` |
| **Block merge on critical issues** | Add a step that fails the job if Claude finds critical bugs |
| **Per-file review** | Loop through changed files and review each separately |
| **Custom rules** | Add your coding standards/guidelines to the system prompt |

---

Given your **Java/Maven/TestNG** setup in the Skillmotion API Automation project, you can also filter the diff to only `.java` files before passing to Claude for more focused reviews. Want me to build that out or add any specific rules for your projects?
