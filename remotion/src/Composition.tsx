import {AbsoluteFill, Sequence, useVideoConfig, Audio, Video, Img} from 'remotion';
import React from 'react';

export const ViralForgeComposition: React.FC<{
  plan: any;
}> = ({plan}) => {
  const {fps} = useVideoConfig();
  const scenes = plan?.scenes || [];

  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      {scenes.map((scene: any, i: number) => {
        const durationInFrames = Math.floor(scene.duration_seconds * fps);
        const startFrame = scenes.slice(0, i).reduce((acc: number, s: any) => acc + Math.floor(s.duration_seconds * fps), 0);

        return (
          <Sequence from={startFrame} durationInFrames={durationInFrames} key={i}>
            <AbsoluteFill>
              {/* Dynamic Subtitles */}
              <div style={{
                position: 'absolute',
                bottom: 150,
                width: '100%',
                textAlign: 'center',
                color: 'white',
                fontSize: 64,
                fontWeight: 'bold',
                textShadow: '0 0 10px rgba(0,0,0,0.8)',
                padding: '0 50px',
                fontFamily: 'Montserrat, sans-serif'
              }}>
                {scene.narration}
              </div>
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
