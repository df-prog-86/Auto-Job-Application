import { Route, Routes } from "react-router-dom";

import { NavShell } from "@/components/NavShell";
import { Accounts } from "@/pages/Accounts";
import { Applications } from "@/pages/Applications";
import { Home } from "@/pages/Home";
import { NeedsAttention } from "@/pages/NeedsAttention";
import { Pairing } from "@/pages/Pairing";
import { Preferences } from "@/pages/Preferences";
import { Profile } from "@/pages/Profile";

export function App() {
  return (
    <Routes>
      <Route element={<NavShell />}>
        <Route index element={<Home />} />
        <Route path="profile" element={<Profile />} />
        <Route path="preferences" element={<Preferences />} />
        <Route path="applications" element={<Applications />} />
        <Route path="needs-attention" element={<NeedsAttention />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="pairing" element={<Pairing />} />
      </Route>
    </Routes>
  );
}
