import { execFileSync } from "node:child_process";
export default function teardown() {
  execFileSync(
    process.env.BACKEND_PYTHON || "../backend/.venv/bin/python",
    [
      "../backend/scripts/cleanup_test_database.py",
      process.env.E2E_DATABASE || "",
    ],
    {
      env: { ...process.env, TEST_MONGODB_URI: process.env.E2E_MONGODB_URI },
      stdio: "inherit",
    },
  );
}
