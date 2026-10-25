import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export type BlockedRepo = {
  id: string;
  repo_url: string;
  repo_name: string;
  reason: string;
  description: string;
  severity: "critical" | "high" | "medium" | "low";
  blocked_by: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export function normalizeRepoUrl(input: string): { normalizedUrl: string; repoName: string } {
  let trimmed = input.trim();
  // Strip trailing slashes and .git
  if (trimmed.endsWith("/")) trimmed = trimmed.slice(0, -1);
  if (trimmed.endsWith(".git")) trimmed = trimmed.slice(0, -4);

  // If user typed owner/repo
  if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
    const parts = trimmed.split("/").filter(Boolean);
    if (parts.length === 2) {
      return {
        normalizedUrl: `https://github.com/${parts[0]}/${parts[1]}`,
        repoName: `${parts[0]}/${parts[1]}`.toLowerCase(),
      };
    }
  }

  try {
    const url = new URL(trimmed);
    const parts = url.pathname.replace(/^\/+/g, "").split("/").filter(Boolean);
    if (parts.length >= 2) {
      const repoName = `${parts[0]}/${parts[1]}`.toLowerCase();
      return {
        normalizedUrl: `https://github.com/${repoName}`,
        repoName,
      };
    }
  } catch {
    // fallback
  }

  return {
    normalizedUrl: trimmed,
    repoName: trimmed.toLowerCase(),
  };
}
