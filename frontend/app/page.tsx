"use client";
import { FormEvent, useState, useEffect } from "react";

type Result = {
  diagnosis: string;
  root_cause: string;
  baseline: { status: string; stdout: string; stderr: string };
  verification: { status: string; stdout: string; stderr: string };
  diff: string;
  modified_files: string[];
  patched_files?: Record<string, string>;
  suggested_repo_name?: string;
  suggested_description?: string;
  deployment?: { repo_url: string; owner: string; repo_name: string };
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STAGES = [
  "Reproducing bug & running baseline tests…",
  "Analyzing test failure with OpenAI…",
  "Validating and applying safe code patch…",
  "Re-running verification tests in isolated workspace…",
];

export default function Home() {
  const [source, setSource] = useState("auto");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [stageIndex, setStageIndex] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  // Deployment state
  const [deployRepoName, setDeployRepoName] = useState("");
  const [deployDesc, setDeployDesc] = useState("");
  const [deployPrivate, setDeployPrivate] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState("");
  const [deployedUrl, setDeployedUrl] = useState("");

  useEffect(() => {
    if (!loading) return;
    const interval = setInterval(() => {
      setStageIndex((prev) => (prev < STAGES.length - 1 ? prev + 1 : prev));
    }, 2500);
    return () => clearInterval(interval);
  }, [loading]);

  async function run(e?: FormEvent) {
    if (e) e.preventDefault();
    setLoading(true);
    setStageIndex(0);
    setError("");
    setResult(null);
    setDeployedUrl("");
    setDeployError("");

    try {
      const response = await fetch(`${API}/api/debug`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source, repository_url: url || null }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Debug run failed");
      }
      setResult(data);
      if (data.suggested_repo_name) {
        setDeployRepoName(data.suggested_repo_name);
      }
      if (data.suggested_description) {
        setDeployDesc(data.suggested_description);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Debug run failed");
    } finally {
      setLoading(false);
    }
  }

  async function deployToGithub() {
    if (!result) return;
    setDeploying(true);
    setDeployError("");
    setDeployedUrl("");

    try {
      const response = await fetch(`${API}/api/deploy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_name: deployRepoName,
          description: deployDesc,
          private: deployPrivate,
          files: result.patched_files || {},
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Deployment failed");
      }
      setDeployedUrl(data.repo_url);
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Deployment failed");
    } finally {
      setDeploying(false);
    }
  }

  return (
    <main>
      <header>
        <span className="mark">BH</span>
        <div>
          <h1>BugHawk</h1>
          <p>AI-powered debugging workspace</p>
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">REPRODUCE · DIAGNOSE · VERIFY</p>
          <h2>
            Turn failing tests into
            <br />
            <em>working code.</em>
          </h2>
          <p className="sub">
            Run a disposable debugging session against a sample project or public GitHub repository.
          </p>
        </div>

        <form onSubmit={run} className="panel">
          <label>PROJECT SOURCE</label>
          <div className="tabs">
            <button
              type="button"
              className={source === "auto" ? "active" : ""}
              onClick={() => setSource("auto")}
            >
              Find my latest GitHub repo
            </button>
            <button
              type="button"
              className={source === "sample" ? "active" : ""}
              onClick={() => setSource("sample")}
            >
              Sample project
            </button>
            <button
              type="button"
              className={source === "github" ? "active" : ""}
              onClick={() => setSource("github")}
            >
              GitHub URL
            </button>
          </div>

          {source === "github" && (
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/owner/repository"
            />
          )}

          {source === "auto" && (
            <div className="sample">
              Latest repository from your authenticated GitHub account <span>Auto-detect · auto-publish</span>
            </div>
          )}

          {source === "sample" && (
            <div className="sample">
              discount-calculator <span>Python · pytest</span>
            </div>
          )}

          <button className="run" disabled={loading}>
            {loading ? "Running BugHawk…" : "Run BugHawk →"}
          </button>
        </form>
      </section>

      {loading && (
        <div className="progress">
          <span>●</span>
          {STAGES[stageIndex]}
          <span>·</span>
          <span>
            Stage {stageIndex + 1} of {STAGES.length}
          </span>
        </div>
      )}

      {error && (
        <div className="error">
          {error}
          <button type="button" onClick={() => run()}>
            Retry
          </button>
        </div>
      )}

      {result && (
        <section className="results">
          <div className="result-head">
            <div>
              <p className="eyebrow">DEBUG SESSION COMPLETE</p>
              <h2>
                {result.verification.status === "passed"
                  ? "Repair verified."
                  : "Repair needs review."}
              </h2>
            </div>
            <span className={`badge ${result.verification.status}`}>
              {result.verification.status}
            </span>
          </div>

          <div className="grid">
            <article>
              <label>ROOT CAUSE</label>
              <p>{result.root_cause || result.diagnosis}</p>
            </article>
            <article>
              <label>MODIFIED FILES</label>
              <p>{result.modified_files.join(", ") || "None"}</p>
            </article>
          </div>

          <article>
            <label>DIAGNOSIS</label>
            <p>{result.diagnosis}</p>
          </article>

          <div className="grid">
            <article>
              <label>BASELINE TESTS · {result.baseline.status.toUpperCase()}</label>
              <pre>{result.baseline.stdout || result.baseline.stderr || "No output"}</pre>
            </article>
            <article>
              <label>VERIFICATION · {result.verification.status.toUpperCase()}</label>
              <pre>{result.verification.stdout || result.verification.stderr || "No output"}</pre>
            </article>
          </div>

          <article>
            <label>BEFORE / AFTER DIFF</label>
            <pre>{result.diff || "No patch was produced."}</pre>
          </article>

          {result.deployment && (
            <div className="deploy-success">
              <p>🎉 Verified code was automatically published to GitHub.</p>
              <a href={result.deployment.repo_url} target="_blank" rel="noreferrer">
                {result.deployment.repo_url} <span>↗</span>
              </a>
            </div>
          )}

          {result.verification.status === "passed" && (
            <article className="deploy-card">
              <div className="deploy-head">
                <div>
                  <label>REDEPLOY TO GITHUB</label>
                  <h3>Publish Verified Code to Reuben123t</h3>
                </div>
                <span className="badge passed">AI Suggested</span>
              </div>

              <div className="deploy-inputs">
                <div className="deploy-field">
                  <label>REPOSITORY NAME</label>
                  <input
                    value={deployRepoName}
                    onChange={(e) => setDeployRepoName(e.target.value)}
                    placeholder="my-new-fixed-repo"
                  />
                </div>

                <div className="deploy-field">
                  <label>DESCRIPTION</label>
                  <input
                    value={deployDesc}
                    onChange={(e) => setDeployDesc(e.target.value)}
                    placeholder="Repository description"
                  />
                </div>

                <div className="deploy-actions">
                  <button
                    type="button"
                    className={`vis-toggle ${deployPrivate ? "active" : ""}`}
                    onClick={() => setDeployPrivate(!deployPrivate)}
                  >
                    {deployPrivate ? "🔒 Private Repo" : "🌐 Public Repo"}
                  </button>

                  <button
                    type="button"
                    className="run deploy-btn"
                    disabled={deploying || !deployRepoName}
                    onClick={deployToGithub}
                  >
                    {deploying ? "Deploying to GitHub…" : "Deploy to My GitHub →"}
                  </button>
                </div>
              </div>

              {deployError && <div className="error" style={{ marginTop: 14 }}>{deployError}</div>}

              {deployedUrl && (
                <div className="deploy-success">
                  <p>🎉 Successfully created & pushed repository to your GitHub!</p>
                  <a href={deployedUrl} target="_blank" rel="noreferrer">
                    {deployedUrl} <span>↗</span>
                  </a>
                </div>
              )}
            </article>
          )}
        </section>
      )}
    </main>
  );
}


