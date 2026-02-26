import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", disabled, ...props }, ref) => {
    return (
      <button
        className={cn(
          "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
          variant === "default" && "bg-slate-900 text-slate-50 hover:bg-slate-800 focus-visible:ring-slate-400",
          variant === "destructive" && "bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-400",
          variant === "outline" && "border border-slate-200 bg-white hover:bg-slate-100 focus-visible:ring-slate-400",
          variant === "secondary" && "bg-slate-100 text-slate-900 hover:bg-slate-200 focus-visible:ring-slate-400",
          variant === "ghost" && "hover:bg-slate-100 focus-visible:ring-slate-400",
          variant === "link" && "text-slate-900 underline-offset-4 hover:underline focus-visible:ring-slate-400",
          size === "default" && "h-10 px-4 py-2",
          size === "sm" && "h-9 rounded-md px-3",
          size === "lg" && "h-11 rounded-md px-8",
          size === "icon" && "h-10 w-10",
          className
        )}
        ref={ref}
        disabled={disabled}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
