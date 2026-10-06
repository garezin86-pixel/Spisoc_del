// Тексты ошибок для экранов входа и регистрации.
//
// Бэкенд отдаёт часть сообщений по-английски (константы в src/core/constants.py),
// и раньше они показывались человеку как есть. Здесь они переводятся по ТОЧНОМУ
// совпадению текста — только те, которые эти экраны реально могут получить.
// Незнакомые сообщения (в том числе уже русские) проходят без изменений.

const BACKEND_MESSAGES = {
    "Invalid credentials": "Неверный логин или пароль",
    "Company account is disabled": "Аккаунт вашей компании отключён. Обратитесь к администратору сервиса.",
    "Account is disabled": "Ваш аккаунт заблокирован. Обратитесь к администратору вашей компании.",
};

function transportError(err) {
    // fetch() упал до ответа (сервер недоступен, нет сети — TypeError) или вернулся
    // не-JSON, например HTML-страница прокси при падении бэкенда (SyntaxError).
    // У таких ошибок нет HTTP-статуса; без перевода человек видел бы
    // «Failed to fetch» / «Unexpected token '<'».
    if (err && err.status === undefined) {
        if (err instanceof TypeError) return "Не удалось связаться с сервером. Проверьте подключение и повторите.";
        if (err instanceof SyntaxError) return "Сервер ответил неожиданно. Попробуйте позже.";
    }
    return null;
}

/** Ошибка входа (пароль и код 2FA). */
export function loginError(err) {
    return transportError(err) || BACKEND_MESSAGES[err?.message] || err?.message || "Не удалось войти";
}

/** Ошибка регистрации (создание компании / вход по приглашению). */
export function registerError(err) {
    const transport = transportError(err);
    if (transport) return transport;
    if (err?.status === 403) {
        return "Создание новых компаний отключено на этом сервере. Попросите ссылку-приглашение у администратора вашей компании.";
    }
    if (err?.status === 429) return "Слишком много попыток. Подождите минуту и повторите.";
    if (err?.message === "User already exists") {
        return "Это имя уже занято в вашей компании. Добавьте, например, отчество или инициал.";
    }
    return BACKEND_MESSAGES[err?.message] || err?.message || "Не удалось зарегистрироваться";
}
