import { useEffect, useRef, useState } from "react";
import { FiChevronDown, FiLogOut } from "react-icons/fi";
import { useAuth } from "../auth/useAuth";
import styles from "./userMenu.module.css";

function getInitials(fullName, email) {
  const source = (fullName || "").trim();
  if (source) {
    const letters = source.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]);
    if (letters.length) return letters.join("").toUpperCase();
  }
  return (email || "?").slice(0, 1).toUpperCase();
}

// Header account control: avatar + name trigger, opens a small popover with
// the signed-in email and a logout action. Only rendered once a user is
// present, so it's safe to mount unconditionally inside AppLayout (which
// itself only renders behind RequireAuth).
function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    const onKeyDown = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!user) return null;

  const initials = getInitials(user.full_name, user.email);
  const displayName = user.full_name || user.email;

  const handleLogout = async () => {
    setOpen(false);
    await signOut();
  };

  return (
    <div className={styles.root} ref={rootRef}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Account menu"
      >
        <span className={styles.avatar} aria-hidden="true">{initials}</span>
        <span className={styles.name}>{displayName}</span>
        <FiChevronDown className={styles.chevron} />
      </button>

      {open && (
        <div className={styles.menu} role="menu">
          <div className={styles.menuHeader}>
            <span className={`${styles.avatar} ${styles.avatarLg}`} aria-hidden="true">{initials}</span>
            <div className={styles.menuIdentity}>
              <p className={styles.menuName}>{displayName}</p>
              <p className={styles.menuEmail}>{user.email}</p>
            </div>
          </div>
          <div className={styles.menuDivider} />
          <button type="button" className={styles.logoutBtn} onClick={handleLogout} role="menuitem">
            <FiLogOut className={styles.logoutIcon} />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

export default UserMenu;
