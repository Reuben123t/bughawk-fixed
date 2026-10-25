import { NextResponse } from "next/server";

export const runtime = "nodejs";

const GITHUB_TOKEN = process.env.GITHUB_TOKEN;

function githubHeaders() {
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  if (GITHUB_TOKEN) {
    headers["Authorization"] = `Bearer ${GITHUB_TOKEN}`;
  }
  return headers;
}

/** Search GitHub for a user by email or username */
async function findGithubUser(query: string): Promise<{
  login: string;
  name: string | null;
  avatar_url: string;
  html_url: string;
  public_repos: number;
  bio: string | null;
} | null> {
  // First try as a direct username
  try {
    const res = await fetch(`https://api.github.com/users/${encodeURIComponent(query)}`, {
      headers: githubHeaders(),
    });
    if (res.ok) {
      const data = await res.json();
      return {
        login: data.login,
        name: data.name,
        avatar_url: data.avatar_url,
        html_url: data.html_url,
        public_repos: data.public_repos,
        bio: data.bio,
      };
    }
  } catch {
    // Fall through to search
  }

  // Try searching by email or name
  try {
    const searchRes = await fetch(
      `https://api.github.com/search/users?q=${encodeURIComponent(query)}&per_page=1`,
      { headers: githubHeaders() }
    );
    if (searchRes.ok) {
      const searchData = await searchRes.json();
      if (searchData.items?.length > 0) {
        const user = searchData.items[0];
        const profileRes = await fetch(`https://api.github.com/users/${user.login}`, {
          headers: githubHeaders(),
        });
        if (profileRes.ok) {
          const profile = await profileRes.json();
          return {
            login: profile.login,
            name: profile.name,
            avatar_url: profile.avatar_url,
            html_url: profile.html_url,
            public_repos: profile.public_repos,
            bio: profile.bio,
          };
        }
      }
    }
  } catch {
    // Fall through
  }

  return null;
}

/** Get top repos for a user */
async function getUserRepos(login: string) {
  const res = await fetch(
    `https://api.github.com/users/${encodeURIComponent(login)}/repos?sort=updated&direction=desc&per_page=12&type=owner`,
    { headers: githubHeaders() }
  );
  if (!res.ok) return [];
  const data = await res.json();
  return (data as any[]).map((r) => ({
    name: r.name,
    full_name: r.full_name,
    html_url: r.html_url,
    description: r.description,
    language: r.language,
    stargazers_count: r.stargazers_count,
    forks_count: r.forks_count,
    open_issues_count: r.open_issues_count,
    updated_at: r.updated_at,
    is_fork: r.fork,
    topics: r.topics,
    default_branch: r.default_branch,
    size: r.size,
  }));
}

/** Use GitHub public events to discover recently active repos */
async function discoverFromPublicFeed(limit = 6): Promise<{
  repo_name: string;
  repo_url: string;
  language: string;
  description: string;
  owner: string;
}[]> {
  try {
    const res = await fetch(`https://api.github.com/events?per_page=100`, {
      headers: githubHeaders(),
    });
    if (!res.ok) return [];
    const events = await res.json();

    const seen = new Set<string>();
    const repos: {
      repo_name: string;
      repo_url: string;
      language: string;
      description: string;
      owner: string;
    }[] = [];

    for (const event of events) {
      if (repos.length >= limit) break;
      const repoName = event?.repo?.name;
      if (!repoName || seen.has(repoName)) continue;
      if (repoName.includes("test") || repoName.includes("demo") || repoName.includes("example")) continue;
      seen.add(repoName);

      try {
        const rRes = await fetch(`https://api.github.com/repos/${repoName}`, {
          headers: githubHeaders(),
        });
        if (rRes.ok) {
          const rData = await rRes.json();
          if (rData.private || rData.fork || rData.archived) continue;
          repos.push({
            repo_name: repoName,
            repo_url: rData.html_url,
            language: rData.language || "Unknown",
            description: rData.description || "",
            owner: rData.owner?.login || "",
          });
        }
      } catch {
        continue;
      }
    }

    return repos;
  } catch {
    return [];
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { action, query, login } = body;

    if (action === "discover_feed") {
      // Discover repos from public event feed
      const repos = await discoverFromPublicFeed(8);
      return NextResponse.json({ success: true, repos });
    }

    if (action === "find_user") {
      if (!query?.trim()) {
        return NextResponse.json({ success: false, error: "Please provide a username or email" }, { status: 400 });
      }
      const user = await findGithubUser(query.trim());
      if (!user) {
        return NextResponse.json({
          success: false,
          error: `No GitHub user found for "${query}". Try a different username or email.`,
        });
      }
      const repos = await getUserRepos(user.login);
      return NextResponse.json({ success: true, user, repos });
    }

    if (action === "get_user_repos") {
      if (!login?.trim()) {
        return NextResponse.json({ success: false, error: "Login required" }, { status: 400 });
      }
      const repos = await getUserRepos(login.trim());
      return NextResponse.json({ success: true, repos });
    }

    return NextResponse.json({ success: false, error: "Unknown action" }, { status: 400 });
  } catch (err: any) {
    return NextResponse.json({ success: false, error: err.message }, { status: 500 });
  }
}
