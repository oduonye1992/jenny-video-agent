import { BrowserRouter, Routes, Route } from "react-router-dom"
import { TooltipProvider } from "@/components/ui/tooltip"
import { RunsList } from "@/pages/RunsList"
import { RunDetail } from "@/pages/RunDetail"
import { ConceptDetail } from "@/pages/ConceptDetail"
import { NewConcept } from "@/pages/NewConcept"
import { NewProject } from "@/pages/NewProject"
import { CreativeReview } from "@/pages/CreativeReview"
import { CharacterGeneration } from "@/pages/CharacterGeneration"
import { DirectorReview } from "@/pages/DirectorReview"
import { ProductionProgress } from "@/pages/ProductionProgress"
import { ShotReview } from "@/pages/ShotReview"

export default function App() {
  return (
    <BrowserRouter>
      <TooltipProvider>
        <main className="dark min-h-screen">
          <Routes>
            <Route path="/" element={<RunsList />} />
            <Route path="/new" element={<NewProject />} />
            <Route path="/new-concept" element={<NewConcept />} />
            <Route path="/concepts/:slug" element={<ConceptDetail />} />
            <Route path="/concepts/:slug/creative" element={<CreativeReview />} />
            <Route path="/concepts/:slug/characters" element={<CharacterGeneration />} />
            <Route path="/concepts/:slug/director" element={<DirectorReview />} />
            <Route path="/concepts/:slug/progress" element={<ProductionProgress />} />
            <Route path="/concepts/:slug/review" element={<ShotReview />} />
            <Route path="/runs/*" element={<RunDetail />} />
          </Routes>
        </main>
      </TooltipProvider>
    </BrowserRouter>
  )
}
