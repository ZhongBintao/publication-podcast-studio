const screen = document.querySelector('.phone-screen');
const progress = document.querySelector('#progress');
const timecode = document.querySelector('#timecode');
const cueNumber = document.querySelector('#cue-number');
const captionEnglish = document.querySelector('.caption-en');
const captionChinese = document.querySelector('.caption-zh');
const questionMetric = document.querySelector('#question-metric');
const englishMetric = document.querySelector('#english-metric');
const chineseMetric = document.querySelector('#chinese-metric');
const validationStatus = document.querySelector('#validation-status');
const image = document.querySelector('.image-slot img');
const imageLabel = document.querySelector('#image-label');
let currentCase = 'normal';

const cues = [
  {
    en: 'For decades, wealth was framed as a reward for risk. Now that argument is shifting.',
    zh: '几十年来，财富常被描述成承担风险后的回报。如今，这种说法正在改变。',
  },
  {
    en: 'The question is not simply who gets rich, but which kinds of wealth society accepts.',
    zh: '问题不只是“谁变得富有”，还包括社会接受哪一种财富。',
  },
  {
    en: 'A new politics of deservingness is taking shape around the billionaire class.',
    zh: '围绕亿万富豪阶层，一种新的“应得性”政治正在形成。',
  },
];

const images = {
  wide: {
    src: '../../output/articles/2026-07-25-print-the-rise-of-the-deserving-rich/assets/01-article-illustration.jpg',
    label: 'ARTICLE IMAGE · LANDSCAPE · 1009×610',
  },
  portrait: {
    src: '../../output/articles/2026-07-25-print-the-rise-of-the-deserving-rich/assets/issue-cover.png',
    label: 'ISSUE COVER · PORTRAIT · 2363×3154',
  },
  cover: {
    src: '../../output/articles/2026-07-25-print-the-rise-of-the-deserving-rich/release/covers/cover-16x9.png',
    label: 'RELEASE COVER · 16:9 · 1920×1080',
  },
};

function englishWords(value) {
  return (value.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).length;
}

function appendWordsWithinLimit(value, maximum, additions) {
  let result = value;
  for (const word of additions) {
    if (result.length + word.length + 1 > maximum) break;
    result += ` ${word}`;
  }
  return result;
}

function appendChineseWithinLimit(value, maximum, additions) {
  let result = value;
  for (const phrase of additions) {
    if (result.length + phrase.length > maximum) break;
    result += phrase;
  }
  return result;
}

const limitEnglishCaption = appendWordsWithinLimit(
  'As wealth changes, society asks which fortunes deserve reward and why it matters.',
  84,
  ['The', 'argument', 'is', 'still', 'shifting.'],
);
const limitChineseCaption = appendChineseWithinLimit(
  '财富来源正在改变，社会开始追问哪些财富值得奖励，以及这为何重要。',
  48,
  ['这种', '说法', '也在', '继续', '变化。'],
);

const testCases = {
  normal: {
    questions: [
      ['What makes a fortune feel deserved?', '什么样的财富会被认为是应得的？'],
      ['Can a new story change the politics of wealth?', '新的财富叙事，能改变政治吗？'],
    ],
    en: 'Wealth was once framed as a reward for risk. That argument is changing.',
    zh: '财富曾被描述成承担风险后的回报。如今，这种说法正在改变。',
  },
  limit: {
    questions: [
      ['How does society decide which fortunes count as deserved when sources of wealth are changing across politics, markets, and public expectations today?', '当财富来源在政治、市场和公众期待中变化时，社会如何判断哪些财富是应得的？'],
      ['Can a new politics of wealth change who receives public trust and why?', '新的财富政治，能改变谁获得公众信任以及为什么吗？'],
    ],
    en: limitEnglishCaption,
    zh: limitChineseCaption,
  },
  over: {
    questions: [
      ['How does society decide which fortunes count as deserved when sources of wealth are changing across politics, institutions, generations, markets, and competing definitions of fairness today?', '当财富来源在政治、制度、世代、市场和不同公平定义之间变化时，社会如何判断哪些财富是应得的？'],
      ['Can a new politics of wealth change who receives public trust, why they receive it, and how that trust reshapes institutions over time?', '新的财富政治能否改变公众信任的对象、原因，以及这种信任如何长期重塑制度？'],
    ],
    en: `${limitEnglishCaption} The argument now reaches beyond the original question and needs a separate cue.`,
    zh: `${limitChineseCaption} 这段字幕也需要拆成多个完整句子后再进入渲染。`,
  },
};

function setPressed(selector, key, value) {
  document.querySelectorAll(selector).forEach((button) => {
    const active = button.dataset[key] === value;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function setCue(index) {
  const cue = cues[index % cues.length];
  if (currentCase === 'normal') {
    captionEnglish.textContent = cue.en;
    captionChinese.textContent = cue.zh;
  }
  const displayNumber = String((index % cues.length) + 1).padStart(2, '0');
  cueNumber.textContent = displayNumber;
}

function renderTestCase(name) {
  const data = testCases[name];
  currentCase = name;
  screen.dataset.caseState = name;
  document.querySelectorAll('.question-card').forEach((card, index) => {
    const [question, translation] = data.questions[index];
    card.querySelector('p').textContent = question;
    card.querySelector('small').textContent = translation;
  });
  captionEnglish.textContent = data.en;
  captionChinese.textContent = data.zh;

  const questionCounts = data.questions.map(([question]) => englishWords(question));
  const maxQuestion = Math.max(...questionCounts);
  const englishCount = data.en.length;
  const chineseCount = data.zh.length;
  questionMetric.textContent = `${maxQuestion} / 22 words`;
  englishMetric.textContent = `${englishCount} / 84 chars`;
  chineseMetric.textContent = `${chineseCount} / 48 chars`;

  const withinBudget = maxQuestion <= 22 && englishCount <= 84 && chineseCount <= 48;
  const nearBudget = maxQuestion >= 20 || englishCount >= 78 || chineseCount >= 44;
  validationStatus.className = 'validation-status';
  if (!withinBudget) {
    validationStatus.classList.add('is-blocked');
    validationStatus.textContent = 'BLOCKED · 超过写稿硬限制，必须先拆分后再渲染。';
  } else if (nearBudget) {
    validationStatus.classList.add('is-warning');
    validationStatus.textContent = 'LIMIT CHECK · 在限制内，但已接近安全上限。';
  } else {
    validationStatus.textContent = 'PASS · 内容长度在写稿预算内。';
  }
}

function renderImage(name) {
  const data = images[name];
  screen.dataset.imageState = name;
  image.src = data.src;
  imageLabel.textContent = data.label;
}

function setTime(value) {
  const seconds = Math.round((Number(value) / 100) * 522);
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  const remainder = (seconds % 60).toString().padStart(2, '0');
  timecode.textContent = `${minutes}:${remainder} / 08:42`;
  setCue(Math.min(cues.length - 1, Math.floor(Number(value) / 34)));
}

document.querySelectorAll('[data-layout]').forEach((button) => {
  button.addEventListener('click', () => {
    const value = button.dataset.layout;
    screen.dataset.layoutState = value;
    setPressed('[data-layout]', 'layout', value);
  });
});

document.querySelectorAll('[data-language]').forEach((button) => {
  button.addEventListener('click', () => {
    const value = button.dataset.language;
    screen.dataset.languageState = value;
    setPressed('[data-language]', 'language', value);
  });
});

document.querySelectorAll('[data-case]').forEach((button) => {
  button.addEventListener('click', () => {
    const value = button.dataset.case;
    setPressed('[data-case]', 'case', value);
    renderTestCase(value);
  });
});

document.querySelectorAll('[data-image]').forEach((button) => {
  button.addEventListener('click', () => {
    const value = button.dataset.image;
    setPressed('[data-image]', 'image', value);
    renderImage(value);
  });
});

document.querySelectorAll('[data-toggle]').forEach((input) => {
  input.addEventListener('change', () => {
    screen.classList.toggle(`show-${input.dataset.toggle}`, input.checked);
  });
});

progress.addEventListener('input', (event) => setTime(event.target.value));
document.querySelector('[data-action="next-cue"]').addEventListener('click', () => {
  const next = (Number(cueNumber.textContent) % cues.length) * 34 + 1;
  progress.value = next;
  setTime(next);
});

setCue(0);
setTime(progress.value);
renderTestCase('normal');
renderImage('wide');
document.querySelectorAll('[data-toggle]').forEach((input) => {
  screen.classList.toggle(`show-${input.dataset.toggle}`, input.checked);
});
