"""Security review script."""
import os
import subprocess

print("=== Security Review ===")
print()

# Check .env handling
print("1. .env file existence:")
if os.path.exists(".env"):
    print("   .env EXISTS - checking content")
    with open(".env") as f:
        content = f.read()
    sensitive_keys = ["MONGODB_URI", "password", "secret", "key", "token"]
    found_sensitive = [k for k in sensitive_keys if k in content.upper()]
    if found_sensitive:
        print(f"   WARNING: .env contains sensitive keys: {found_sensitive}")
    else:
        print("   .env content appears safe (no obvious sensitive keys)")
else:
    print("   .env does NOT exist")

print()

print("2. .env.example existence:")
if os.path.exists(".env.example"):
    print("   .env.example EXISTS")
    with open(".env.example") as f:
        content = f.read()
    has_placeholder = "your_" in content or "placeholder" in content.lower()
    print(f"   Has placeholder pattern: {has_placeholder}")
    lines = content.strip().split("\n")
    for line in lines[:5]:
        print(f"     {line}")
else:
    print("   .env.example does NOT exist")

print()

print("3. .gitignore existence:")
if os.path.exists(".gitignore"):
    print("   .gitignore EXISTS")
    with open(".gitignore") as f:
        content = f.read()
    if ".env" in content:
        print("   .gitignore references .env")
    else:
        print("   .gitignore does NOT reference .env")
else:
    print("   .gitignore does NOT exist")

print()

print("4. Git status for secrets:")
result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=".")
git_status = result.stdout
if git_status:
    lines = git_status.strip().split("\n")
    print(f"   Total changed files: {len(lines)}")
    env_changes = [l for l in lines if ".env" in l]
    if env_changes:
        print(f"   WARNING: .env files in git changes: {env_changes}")
    else:
        print("   No .env files in git changes")
else:
    print("   No git changes")

print()

print("5. Check source files for hardcoded credentials:")
issues = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".pytest_cache")]
    for fname in files:
        if fname.endswith(".py"):
            fpath = os.path.join(root, fname)
            try:
                with open(fpath) as fh:
                    c = fh.read()
                    # Check for actual credential exposure (not just references)
                    if "MONGODB_URI" in c:
                        # Count actual URI assignments (not just config imports)
                        uri_lines = [l for l in c.split("\n") if "MONGODB_URI" in l and "://" in l]
                        if len(uri_lines) > 2:
                            issues.append(f"{fpath}: multiple MONGODB_URI values")
            except Exception:
                pass

if not issues:
    print("   No critical hardcoded credential issues found")
else:
    for issue in issues:
        print(f"   {issue}")

print()
print("=== Security Review Complete ===")