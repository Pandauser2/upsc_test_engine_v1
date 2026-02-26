"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { UploadForm } from "@/components/UploadForm";
import { getToken, setToken, clearToken, login, apiUrl } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [token, setTokenState] = useState<string | null>(null);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [pageError, setPageError] = useState("");

  useEffect(() => {
    setTokenState(getToken());
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError("");
    try {
      const res = await login(loginEmail, loginPassword);
      setToken(res.access_token);
      setTokenState(res.access_token);
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : "Login failed.");
    }
  };

  const handleLogout = () => {
    clearToken();
    setTokenState(null);
  };

  const handleGenerationStarted = (testId: string) => {
    router.push(`/tests/${testId}`);
  };

  if (token === null) {
    return (
      <main className="min-h-screen bg-slate-50 p-8">
        <div className="mx-auto max-w-sm">
          <Card>
            <CardHeader>
              <CardTitle>Sign in</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium">Email</label>
                  <Input
                    type="email"
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium">Password</label>
                  <Input
                    type="password"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    required
                  />
                </div>
                {loginError && <p className="text-sm text-red-600">{loginError}</p>}
                <Button type="submit">Sign in</Button>
              </form>
              <p className="mt-4 text-xs text-slate-500">
                Backend: {apiUrl("")}. Register at POST /auth/register if needed.
              </p>
            </CardContent>
          </Card>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50 p-8">
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">UPSC Test Engine</h1>
          <Button variant="outline" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </div>
        {pageError && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {pageError}
          </div>
        )}
        <UploadForm onGenerationStarted={handleGenerationStarted} onError={setPageError} />
      </div>
    </main>
  );
}
