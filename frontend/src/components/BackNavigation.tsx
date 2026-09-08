import { Link } from "react-router-dom";
import type { To } from "react-router-dom";

type BackNavigationProps =
  | {
      label: string;
      replace?: boolean;
      to: To;
      onClick?: never;
    }
  | {
      label: string;
      onClick: () => void;
      replace?: never;
      to?: never;
    };

function BackArrowIcon() {
  return (
    <svg
      aria-hidden="true"
      className="back-navigation-icon"
      fill="none"
      focusable="false"
      height="20"
      viewBox="0 0 20 20"
      width="20"
    >
      <path
        d="M16 10H4M9 5l-5 5 5 5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}

export function BackNavigation(props: BackNavigationProps) {
  if (props.to !== undefined) {
    return (
      <Link
        aria-label={props.label}
        className="back-navigation"
        replace={props.replace}
        title={props.label}
        to={props.to}
      >
        <BackArrowIcon />
      </Link>
    );
  }

  return (
    <button
      aria-label={props.label}
      className="back-navigation"
      onClick={props.onClick}
      title={props.label}
      type="button"
    >
      <BackArrowIcon />
    </button>
  );
}
