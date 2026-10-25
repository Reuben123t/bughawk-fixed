import { NextResponse } from "next/server";

export const runtime = "nodejs";

const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

function githubHeaders() {
  const token = GITHUB_TOKEN;
  if (!token) throw new Error("GITHUB_TOKEN is not set");
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
  };
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { action } = body;

    if (action === "analyze_and_fix") {
      /**
       * Calls the Python backend to:
       * 1. Clone the repo
       * 2. Run tests (baseline)
       * 3. AI diagnose & patch
       * 4. Verify fix
       * 5. Deploy as new GitHub repo (auto_deploy=true)
       */
      const { repo_url, deploy_private = false } = body;

      if (!repo_url?.trim()) {
        return NextResponse.json({ success: false, error: "repo_url is required" }, { status: 400 });
      }

      const res = await fetch(`${API_URL}/api/debug`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "github",
          repository_url: repo_url,
          auto_deploy: true,
          deploy_private,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        return NextResponse.json(
          { success: false, error: data.detail || "Analysis failed", raw: data },
          { status: res.status }
        );
      }

      return NextResponse.json({
        success: true,
        diagnosis: data.diagnosis,
        root_cause: data.root_cause,
        diff: data.diff,
        modified_files: data.modified_files,
        baseline: data.baseline,
        verification: data.verification,
        deployment: data.deployment,
        suggested_repo_name: data.suggested_repo_name,
        suggested_description: data.suggested_description,
        patched_files: data.patched_files,
      });
    }

    if (action === "deploy_files") {
      /**
       * Directly deploy provided files to a new GitHub repo.
       * Calls the Python backend /api/deploy.
       */
      const { repo_name, description, private: isPrivate = false, files } = body;

      if (!repo_name || !files) {
        return NextResponse.json({ success: false, error: "repo_name and files required" }, { status: 400 });
      }

      const res = await fetch(`${API_URL}/api/deploy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_name, description, private: isPrivate, files }),
      });

      const data = await res.json();

      if (!res.ok) {
        return NextResponse.json(
          { success: false, error: data.detail || "Deploy failed" },
          { status: res.status }
        );
      }

      return NextResponse.json({ success: true, ...data });
    }

    if (action === "generate_and_upload") {
      /**
       * AI-generate new code from a prompt, then upload as a new repo.
       * Uses OpenAI to create the code, then deploys via Python backend.
       */
      const { prompt, repo_name, description, private: isPrivate = false } = body;

      const openAiKey = process.env.OPENAI_API_KEY;
      if (!openAiKey) {
        return NextResponse.json({ success: false, error: "OPENAI_API_KEY not configured" }, { status: 503 });
      }

      const systemPrompt = `You are a code generator. Generate a complete, working project based on the user's description.
Return JSON with keys:
- files: object where keys are relative file paths and values are file content strings
- language: primary language
- readme: a good README.md content
- repo_name: suggested short, lowercase, hyphenated repo name (override if user provided one)
- description: 1-sentence project description

Generate at minimum: README.md, main source file(s), requirements/package.json if needed, and a basic test file.
Make it complete and actually runnable. Focus on Python unless the user specifies otherwise.`;

      const aiRes = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${openAiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: "gpt-4o-mini",
          temperature: 0.3,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: `Project: ${prompt}${repo_name ? `\nRepo name: ${repo_name}` : ""}` },
          ],
        }),
      });

      if (!aiRes.ok) {
        const aiErr = await aiRes.json();
        return NextResponse.json({ success: false, error: `AI error: ${aiErr.error?.message || "Unknown"}` }, { status: 502 });
      }

      const aiData = await aiRes.json();
      let generated: any;
      try {
        generated = JSON.parse(aiData.choices[0].message.content);
      } catch {
        return NextResponse.json({ success: false, error: "AI returned invalid JSON" }, { status: 502 });
      }

      const finalRepoName = repo_name || generated.repo_name || "ai-generated-project";
      const finalDesc = description || generated.description || "Generated by BugHawk AI";
      const files: Record<string, string> = generated.files || {};

      if (generated.readme && !files["README.md"]) {
        files["README.md"] = generated.readme;
      }

      // Deploy to GitHub via Python backend
      const deployRes = await fetch(`${API_URL}/api/deploy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_name: finalRepoName,
          description: finalDesc,
          private: isPrivate,
          files,
        }),
      });

      const deployData = await deployRes.json();

      if (!deployRes.ok) {
        return NextResponse.json(
          {
            success: false,
            error: deployData.detail || "Deploy failed",
            generated_files: files,
          },
          { status: deployRes.status }
        );
      }

      return NextResponse.json({
        success: true,
        ...deployData,
        generated_files: files,
        language: generated.language,
        description: finalDesc,
      });
    }

    return NextResponse.json({ success: false, error: "Unknown action" }, { status: 400 });
  } catch (err: any) {
    return NextResponse.json({ success: false, error: err.message }, { status: 500 });
  }
}
