import { useLocation, useNavigate } from "react-router-dom";

import { BackNavigation } from "./BackNavigation";
import { resolveReturnLocation } from "../features/navigation/returnLocation";

export function AuxiliaryPageReturn() {
  const location = useLocation();
  const navigate = useNavigate();
  const decision = resolveReturnLocation(location.state);

  if (decision.kind === "invalid") {
    return (
      <div aria-label="返回工作页面" className="action-row">
        <span role="status">返回来源无效</span>
        <BackNavigation label="返回项目首页" replace to="/" />
      </div>
    );
  }

  const target = decision.kind === "valid" ? decision.location : { pathname: "/" };
  const label =
    decision.kind === "valid" && decision.location.pathname !== "/"
      ? "返回刚才页面"
      : "返回项目首页";

  return (
    <div aria-label="返回工作页面" className="action-row">
      <BackNavigation
        label={label}
        onClick={() => navigate(target, { replace: true })}
      />
    </div>
  );
}
