import { createRoot } from "react-dom/client";

import App from "./App";
import { initializeTheme } from "./features/theme/theme";
import "./styles.css";

initializeTheme();
createRoot(document.getElementById("root")!).render(<App />);
