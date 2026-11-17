import CallScreen from "./CallScreen";
import StaffConsole from "./StaffConsole";

export default function App() {
  return location.pathname.startsWith("/staff") ? <StaffConsole /> : <CallScreen />;
}
