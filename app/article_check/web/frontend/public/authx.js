const HOST = "http://124.71.226.114:8444";
const API = {
    OAUTH: {
        AUTH: HOST + "/api/oauth/auth",        // 获取授权URL
        TOKEN: HOST + "/api/oauth/token",      // 获取token
        REFRESH: HOST + "/api/oauth/refresh",  // 刷新token
        INTROSPECT: HOST + "/api/oauth/introspect" // 校验token
    }
};

auth().then(r => {
    if(!r){
        //处理认证错误逻辑，例如跳转404页面
        alert("认证出错")
    }
});

async function auth() {
    const paramsString = window.location.search;

    const pathParams = new URLSearchParams(paramsString);

    const code = pathParams.get('code');
    const state = pathParams.get('state');

    if (!code){
        if (!localStorage.getItem("access_token")){
            // 跳转授权页面
            return await redirect();
        } else {
            // 检查token是否过期
            const expires_in = localStorage.getItem("expires_in");
            if (expires_in && Date.now() > expires_in){ // token过期
                // 刷新token
                return await refreshToken()
            } else {
                // 校验token
                return await introspectToken()
            }
        }
    } else {
        console.log("code:", code);
        console.log("state:", state);
        //请求token
        const res = await getToken(code, state);
        // 清除 URL 中的查询参数
        window.history.replaceState({}, document.title, window.location.pathname);
        return res
    }
}

async function redirect() {
    const redirectUri = window.location.origin + window.location.pathname;
    const url = `${API.OAUTH.AUTH}?redirectUri=${encodeURIComponent(redirectUri)}`;
    const requestOptions = {
        method: "GET",
        redirect: "follow"
    };

    try {
        const response = await fetch(url, requestOptions);
        const resultStr = await response.text();
        const result = JSON.parse(resultStr);

        console.log("auth_url:", result.auth_url);
        console.log("state:", result.state);
        window.location.href = result.auth_url; // 跳转授权页面
        return true;
    } catch (error) {
        console.error('Error:', error);
        return false;
    }
}

async function getToken(code, state) {
    const myHeaders = new Headers();
    myHeaders.append("Content-Type", "application/json");
    const raw = JSON.stringify({
        "code": code,
        "redirect_uri": window.location.origin + window.location.pathname
    });

    const requestOptions = {
        method: "POST",
        headers: myHeaders,
        body: raw,
        redirect: "follow"
    };

    try {
        const response = await fetch(API.OAUTH.TOKEN, requestOptions);
        const resultStr = await response.text();
        const result = JSON.parse(resultStr);

        console.log("access_token:", result.access_token);
        console.log("expires_in:", Date.now() + (result.expires_in * 1000));
        console.log("refresh_token:", result.refresh_token);
        console.log("id_token:", result.id_token);
        localStorage.setItem("access_token", result.access_token);
        localStorage.setItem("refresh_token", result.refresh_token);
        localStorage.setItem("id_token", result.id_token);

        return true;
    } catch (error) {
        console.error('Error:', error);
        return  false;
    }
}

async function refreshToken(){
    const myHeaders = new Headers();
    myHeaders.append("Content-Type", "application/json");

    const raw = JSON.stringify({
        "refresh_token": localStorage.getItem("refresh_token")
    });

    const requestOptions = {
        method: "POST",
        headers: myHeaders,
        body: raw,
        redirect: "follow"
    };

    try {
        const response = await fetch(API.OAUTH.REFRESH, requestOptions);
        const resultStr = await response.text();
        const result = JSON.parse(resultStr);

        console.log("access_token:", result.access_token);
        console.log("expires_in:", Date.now() + (result.expires_in * 1000));
        console.log("refresh_token:", result.refresh_token);
        console.log("id_token:", result.id_token);
        localStorage.setItem("access_token", result.access_token);
        localStorage.setItem("expires_in", Date.now() + (result.expires_in * 1000));
        localStorage.setItem("refresh_token", result.refresh_token);
        localStorage.setItem("id_token", result.id_token);

        return true;
    } catch (error) {
        console.error('Error:', error);
        return  false;
    }
}

async function introspectToken(){
    const myHeaders = new Headers();
    myHeaders.append("Content-Type", "application/json");

    const raw = JSON.stringify({
        "token": localStorage.getItem("access_token")
    });

    const requestOptions = {
        method: "POST",
        headers: myHeaders,
        body: raw,
        redirect: "follow"
    };

    try {
        const response = await fetch(API.OAUTH.INTROSPECT, requestOptions);
        const resultStr = await response.text();
        const result = JSON.parse(resultStr);
        console.log(result)
        if (!result.active === true) {
            await redirect()
        }
        return true;
    } catch (error) {
        console.error('Error:', error);
        return false;
    }
}
