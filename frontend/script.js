let currentRound = "Communication";
const roundSequence = ["Communication", "Technical", "HR"];
let timerInterval = null;
let roundEnded = false;

const roundDurations = {
  Communication: 120,
  Technical: 300,
  HR: 120
};

function setBlinking(speaker) {
  document.getElementById("aiIcon").classList.remove("blink");
  document.getElementById("userIcon").classList.remove("blink");

  if (speaker === "ai") {
    document.getElementById("aiIcon").classList.add("blink");
    setStatus("AI is speaking...");
  } else if (speaker === "user") {
    document.getElementById("userIcon").classList.add("blink");
    setStatus("Listening for your response...");
  } else {
    setStatus("Waiting...");
  }
}

function setStatus(text) {
  document.getElementById("status").innerText = text;
}

function updateTimer(secondsLeft) {
  const min = String(Math.floor(secondsLeft / 60)).padStart(2, '0');
  const sec = String(secondsLeft % 60).padStart(2, '0');
  document.getElementById("timerDisplay").innerText = `🕒 Time Left: ${min}:${sec}`;
}

function startCountdown(duration) {
  let remaining = duration;
  updateTimer(remaining);

  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    remaining--;
    updateTimer(remaining);
    if (remaining <= 0) {
      clearInterval(timerInterval);
    }
  }, 1000);
}

async function playAudio(path, fallbackText) {
  if (!path) {
    console.warn("No audio path provided.");
    return;
  }

  try {
    const audio = new Audio(path);
    audio.oncanplay = () => console.log("✅ Audio ready to play:", path);
    audio.onerror = (e) => console.error("❌ Audio load error:", e);

    await audio.play();

    return new Promise(resolve => {
      audio.onended = () => {
        setBlinking(null);
        resolve();
      };
    });
  } catch (e) {
    console.error("❌ Audio playback error:", e);
  }
}

function unlockAudioThenStart() {
  const unlock = new Audio();
  unlock.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YRAAAA=="; // Silent unlock audio
  unlock.play().catch(() => {});
  startInterview();
}

async function startInterview() {
  document.getElementById("startInterviewBtn").style.display = "none";
  document.getElementById("nextRoundBtn").style.display = "none";
  document.getElementById("restartInterviewBtn").style.display = "none";
  document.getElementById("evaluation").style.display = "none";
  document.getElementById("summaryText").innerText = "";
  setBlinking("ai");
  roundEnded = false;

  const res = await fetch(`/start_round?round_name=${currentRound}`);
  const data = await res.json();

  document.getElementById("roundLabel").innerText = `Round: ${currentRound}`;
  startCountdown(roundDurations[currentRound]);

  await playAudio(data.audio_path, data.message);
  startVoiceLoop();
}

async function startVoiceLoop() {
  if (roundEnded) return;

  setBlinking("user");
  const res = await fetch("/record_and_respond", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ round: currentRound })
  });

  const data = await res.json();
  setBlinking(null);

  if (data.response && (
      data.response.includes("Please proceed to the next round") ||
      data.response.includes("Thank you for completing the interview")
  )) {
    roundEnded = true;
    await playAudio(data.audio_path, data.response);

    const currentIdx = roundSequence.indexOf(currentRound);
    if (currentIdx < roundSequence.length - 1) {
      document.getElementById("nextRoundBtn").style.display = "inline-block";
    } else {
      setStatus("✅ Interview complete. Generating evaluation...");
      const evalRes = await fetch("/evaluate");
      const summaryData = await evalRes.json();

      document.getElementById("evaluation").style.display = "block";
      document.getElementById("summaryText").innerText = summaryData.summary;

      await playAudio(null, summaryData.summary);
      setStatus("🎉 Thank you for participating in the mock interview!");
      document.getElementById("restartInterviewBtn").style.display = "inline-block";
    }
    return;
  }

  if (data.response && data.audio_path) {
    setBlinking("ai");
    await playAudio(data.audio_path, data.response);
    setTimeout(() => startVoiceLoop(), 500);
  } else {
    setTimeout(() => startVoiceLoop(), 1000);
  }
}

async function startNextRound() {
  const res = await fetch(`/next_round?current_round=${currentRound}`);
  const data = await res.json();

  if (data.next_round) {
    currentRound = data.next_round;
    document.getElementById("nextRoundBtn").style.display = "none";
    startInterview();
  } else {
    roundEnded = true;
    clearInterval(timerInterval);
    document.getElementById("nextRoundBtn").style.display = "none";

    setStatus("✅ Interview complete. Generating evaluation...");
    const evalRes = await fetch("/evaluate");
    const summaryData = await evalRes.json();

    document.getElementById("evaluation").style.display = "block";
    document.getElementById("summaryText").innerText = summaryData.summary;

    await playAudio(null, summaryData.summary);
    setStatus("🎉 Thank you for participating in the mock interview!");
    document.getElementById("restartInterviewBtn").style.display = "inline-block";
  }
}

function restartInterview() {
  currentRound = "Communication";
  roundEnded = false;
  document.getElementById("evaluation").style.display = "none";
  document.getElementById("summaryText").innerText = "";
  document.getElementById("restartInterviewBtn").style.display = "none";
  document.getElementById("nextRoundBtn").style.display = "none";
  document.getElementById("status").innerText = "Restarting...";
  startInterview();
}
