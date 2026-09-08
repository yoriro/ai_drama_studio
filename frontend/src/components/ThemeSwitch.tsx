import type { Theme } from "../features/theme/theme";

interface ThemeSwitchProps {
  notice: string | null;
  onThemeChange: (theme: Theme) => void;
  theme: Theme;
}

const options: Array<{ label: string; value: Theme }> = [
  { label: "暗色", value: "dark" },
  { label: "亮色", value: "light" },
];

export function ThemeSwitch({
  notice,
  onThemeChange,
  theme,
}: ThemeSwitchProps) {
  return (
    <div aria-label="外观主题" className="theme-switch" role="group">
      {options.map((option) => (
        <button
          aria-pressed={theme === option.value}
          key={option.value}
          onClick={() => onThemeChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
      {notice !== null && (
        <p className="theme-switch-notice" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
