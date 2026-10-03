/**
 * LoginPage — credential form for the Mediflow OS HMIS.
 *
 * Uses react-hook-form + zod for validation and calls the SimpleJWT token
 * endpoint via TanStack Query mutation. On success, tokens are stored in
 * authStore and the user is redirected to the dashboard.
 */

import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { Activity, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuthStore } from "@/stores/authStore";
import { login } from "./auth.api";

const loginSchema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      setTokens(data.access, data.refresh);
      void navigate("/dashboard");
    },
  });

  const onSubmit = (values: LoginFormValues) => {
    mutation.mutate(values);
  };

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-12 items-center justify-center rounded-xl bg-primary">
            <Activity className="size-6 text-primary-foreground" aria-hidden="true" />
          </div>
          <CardTitle className="text-2xl">Mediflow OS</CardTitle>
          <CardDescription>Sign in to your hospital workspace</CardDescription>
        </CardHeader>

        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="flex flex-col gap-4">
              {mutation.isError && (
                <p
                  role="alert"
                  className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  Invalid credentials. Please try again.
                </p>
              )}

              <div className="grid gap-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  type="text"
                  autoComplete="username"
                  aria-invalid={errors.username ? true : undefined}
                  aria-describedby={errors.username ? "username-error" : undefined}
                  {...register("username")}
                />
                {errors.username && (
                  <p id="username-error" className="text-sm text-destructive">
                    {errors.username.message}
                  </p>
                )}
              </div>

              <div className="grid gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  aria-invalid={errors.password ? true : undefined}
                  aria-describedby={errors.password ? "password-error" : undefined}
                  {...register("password")}
                />
                {errors.password && (
                  <p id="password-error" className="text-sm text-destructive">
                    {errors.password.message}
                  </p>
                )}
              </div>

              <Button type="submit" className="w-full" disabled={mutation.isPending}>
                {mutation.isPending ? (
                  <>
                    <Loader2 className="animate-spin" aria-hidden="true" />
                    Signing in…
                  </>
                ) : (
                  "Sign in"
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
