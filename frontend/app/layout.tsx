import "./styles.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "RepoBlock | Open Repository Check Blocker & Community Shield",
  description:
    "Completely open community repository blocking platform. Block specific repositories from being checked, audited, or executed. Real-time verification and policy enforcement powered by Supabase.",
};

export default function Layout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
