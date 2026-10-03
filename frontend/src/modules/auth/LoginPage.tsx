/**
 * LoginPage — credential form for Mediflow OS HMIS.
 *
 * Spec: UI_UX_design §7 Sign-in (/auth/sign-in) and design.md §6.1
 * - Centered 420px card on #f8fafc canvas, teal primary CTA, SSO secondary
 * - RHF + Zod validation, accessible labels/error association
 * - Password visibility toggle (aria-label), inline field errors, alert on server error
 * - Responsive single-column, primary CTA visible without scroll
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { Activity, Loader2, Eye, EyeOff } from "lucide-react";

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
  username: z.string().min(2, "Enter your work username or email."),
  password: z.string().min(8, "Password is required (min 8 characters)."),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      setTokens(data.access, data.refresh);
      void navigate("/", { replace: true });
    },
  });

  const onSubmit = (values: LoginFormValues) => {
    mutation.mutate(values);
  };

  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted p-4">
      {/* Brand mark — above the card, max 220px as per design §2.4 */}
      <div className="mb-6 flex flex-col items-center gap-2 text-center">
        <div className="flex size-10 items-center justify-center rounded-xl bg-primary shadow-sm">
          <Activity className="size-5 text-primary-foreground" aria-hidden="true" />
        </div>
        <div>
          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted-foreground">
            HIMS · HOSPITAL INFORMATION MANAGEMENT SYSTEM
          </p>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Mediflow OS</h1>
        </div>
      </div>

      <Card className="w-full max-w-[420px] border bg-card shadow-sm">
        <CardHeader className="pb-4 text-center">
          <CardTitle className="text-xl text-card-foreground">Sign in</CardTitle>
          <CardDescription>Enter your work credentials to continue</CardDescription>
        </CardHeader>

        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
            {mutation.isError && (
              <p
                role="alert"
                className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                Invalid credentials. Please check your username and password and try again.
              </p>
            )}

            <div className="grid gap-1.5">
              <Label htmlFor="username">Email / User ID</Label>
              <Input
                id="username"
                type="text"
                autoComplete="username"
                placeholder="name@hospital.in"
                aria-invalid={errors.username ? true : undefined}
                aria-describedby={errors.username ? "username-error" : undefined}
                autoFocus
                {...register("username")}
              />
              {errors.username && (
                <p id="username-error" className="text-sm text-destructive">
                  {errors.username.message}
                </p>
              )}
            </div>

            <div className="grid gap-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                <a href="#" className="text-xs font-medium text-primary hover:underline" onClick={(e) => e.preventDefault()}>
                  Forgot password?
                </a>
              </div>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="pr-10"
                  aria-invalid={errors.password ? true : undefined}
                  aria-describedby={errors.password ? "password-error" : undefined}
                  {...register("password")}
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? (
                    <EyeOff className="size-4" aria-hidden="true" />
                  ) : (
                    <Eye className="size-4" aria-hidden="true" />
                  )}
                </button>
              </div>
              {errors.password && (
                <p id="password-error" className="text-sm text-destructive">
                  {errors.password.message}
                </p>
              )}
            </div>

            <Button type="submit" className="h-11 w-full text-sm font-semibold" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </Button>

            <div className="flex items-center gap-3 py-1">
              <span className="h-px flex-1 bg-border" aria-hidden="true" />
              <span className="text-xs font-medium text-muted-foreground">OR</span>
              <span className="h-px flex-1 bg-border" aria-hidden="true" />
            </div>

            <Button type="button" variant="outline" className="h-11 w-full" onClick={() => {}}>
              Continue with SSO
            </Button>

            <p className="pt-1 text-center text-xs leading-relaxed text-muted-foreground">
              Secure hospital access — your session is audited. Use your hospital-issued credentials.
            </p>
          </form>
        </CardContent>
      </Card>

      <p className="mt-6 text-center text-xs text-muted-foreground">
        Protected health information · Access is logged and monitored
      </p>
    </div>
  );
}
