import { useEffect, useState } from "react";
import {
  applyThemeAttribute,
  readStoredTheme,
  storeTheme,
  subscribeSystemTheme,
  systemTheme,
} from "./theme";
import styles from "./appLayout.module.css";

const OPTIONS = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

// Header Light/Dark segmented control. Until the user picks one, the app
// follows the OS setting (live) and the control just reflects it; a pick is
// stored and then wins on every later visit.
function ThemeToggle() {
  const [override, setOverride] = useState(readStoredTheme);
  const [system, setSystem] = useState(systemTheme);

  useEffect(() => subscribeSystemTheme(setSystem), []);

  useEffect(() => {
    applyThemeAttribute(override);
  }, [override]);

  const effective = override ?? system;

  const choose = (value) => {
    storeTheme(value);
    setOverride(value);
  };

  return (
    <div className={styles.themeToggle} role="group" aria-label="Color theme">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`${styles.themeOption} ${effective === opt.value ? styles.themeOptionActive : ""}`}
          aria-pressed={effective === opt.value}
          onClick={() => choose(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default ThemeToggle;
