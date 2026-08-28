import PropTypes from "prop-types";
import GradientText from "./GradientText";
import SideRays from "./SideRays";
import ScrollVelocity from "./ScrollVelocity";
import HeroGlow from "./HeroGlow";

function HeroSection() {
  const gradientColors = [
    "#0F172A",
    "#1E293B",
    "#2563EB",
    "#1E293B",
    "#0F172A",
  ];

  return (
    <section className="recon-hero-exec" aria-label="Executive hero">
      <SideRays
        speed={2.5}
        rayColor1="#EAB308"
        rayColor2="#96c8ff"
        intensity={2}
        spread={2}
        origin="top-right"
        tilt={0}
        saturation={1.5}
        blend={0.75}
        falloff={1.6}
        opacity={1}
      />


      <HeroGlow />

      <div className="recon-hero-exec-inner">
        <div className="recon-hero-badge" data-recon-hero-badge>
          AI-Powered Enterprise Reconciliation Platform
        </div>

        <h1 className="recon-hero-exec-title" data-recon-hero-title>
          <GradientText
            colors={gradientColors}
            animationSpeed={12}
            direction="horizontal"
          >
            Enterprise Reconciliation Intelligence
          </GradientText>
        </h1>

        <div className="recon-hero-exec-subtitle" data-recon-hero-subtitle>
          Compare. Explain. Resolve.
        </div>

        <p className="recon-hero-exec-desc" data-recon-hero-desc>
          AI-powered reconciliation, variance analysis, and executive-ready
          reporting for enterprise planning and operational data.
        </p>

        <div className="recon-hero-divider" aria-hidden="true" />

        <div className="recon-hero-ticker-wrap" data-recon-hero-ticker>
          <ScrollVelocity
            velocity={10}
            numCopies={4}
            items={[
              "Secure",
              "Explainable",
              "Auditable",
              "Transparent",
              "Traceable",
              "Trusted Data",
              "Accuracy",
              "Accountability",
              "Enterprise Ready",
            ]}
          />
        </div>


      </div>
    </section>
  );
}

HeroSection.propTypes = {
  // no props
};

export default HeroSection;


