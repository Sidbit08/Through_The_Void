(() => {
  const control = document.getElementById('sound-control');
  if (!control) return;
  let context, noise, volume;
  function update() {
    const playing = context && context.state === 'running';
    control.textContent = playing ? 'Mute sound' : 'Enable sound';
    control.setAttribute('aria-pressed', String(Boolean(playing)));
  }
  async function toggle() {
    try {
      if (!context) {
        const Audio = window.AudioContext || window.webkitAudioContext;
        context = new Audio();
        const buffer = context.createBuffer(1, context.sampleRate * 3, context.sampleRate);
        const samples = buffer.getChannelData(0);
        for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
        noise = context.createBufferSource();
        noise.buffer = buffer;
        noise.loop = true;
        volume = context.createGain();
        volume.gain.value = 0.008;
        noise.connect(volume).connect(context.destination);
        noise.start();
        context.addEventListener('statechange', update);
        await context.resume();
      } else if (context.state === 'running') await context.suspend();
      else await context.resume();
    } catch (_) { /* A browser may refuse audio; the control stays honest. */ }
    update();
  }
  control.addEventListener('click', toggle);
  update();
})();
