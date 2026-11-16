import { Connect } from "./pages/Connect"
import { Demo } from "./pages/Demo"
import { Home } from "./pages/Home"
import { Lesson } from "./pages/Lesson"
import { Missing } from "./pages/Missing"
import { useRoute } from "./lib/router"

export function App() {
  const route = useRoute()
  switch (route.page) {
    case "home":
      return <Home />
    case "lesson":
      return <Lesson key={route.id} id={route.id} />
    case "demo":
      return <Demo />
    case "connect":
      return <Connect />
    default:
      return <Missing />
  }
}
