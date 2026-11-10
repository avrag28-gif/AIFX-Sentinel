#property strict
#property version "1.00"
#property description "AIFX Sentinel telemetry bridge. No order execution."

input string InpApiBase = "http://sentinel-api:8000";
input string InpBridgeToken = "";
input string InpSymbol = "EURUSD";
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M5;
input int InpHeartbeatSeconds = 30;

string JsonEscape(string s) {
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   return s;
}
bool PostJson(string path, string body) {
   char data[], result[];
   string headers = "Content-Type: application/json\r\nX-AIFX-Token: " + InpBridgeToken + "\r\n";
   StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(data)>0) ArrayResize(data, ArraySize(data)-1);
   string response_headers;
   ResetLastError();
   int code = WebRequest("POST", InpApiBase + path, headers, 5000, data, result, response_headers);
   if(code < 200 || code >= 300) {
      Print("AIFX bridge HTTP error=", code, " lastError=", GetLastError());
      return false;
   }
   return true;
}
void SendHeartbeat() {
   string body = "{\"terminal\":\"MetaTrader 5\",\"account_login\":\""+
      IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN))+"\",\"server\":\""+
      JsonEscape(AccountInfoString(ACCOUNT_SERVER))+"\",\"connected\":"+
      (TerminalInfoInteger(TERMINAL_CONNECTED) ? "true":"false")+",\"note\":\"telemetry-only\"}";
   PostJson("/v1/heartbeat", body);
}
void SendClosedCandle() {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(InpSymbol, InpTimeframe, 1, 1, r) != 1) return;
   string tf = EnumToString(InpTimeframe);
   StringReplace(tf, "PERIOD_", "");
   string body = "{\"symbol\":\""+JsonEscape(InpSymbol)+"\",\"timeframe\":\""+tf+
      "\",\"time\":"+IntegerToString((long)r[0].time)+
      ",\"open\":"+DoubleToString(r[0].open,_Digits)+
      ",\"high\":"+DoubleToString(r[0].high,_Digits)+
      ",\"low\":"+DoubleToString(r[0].low,_Digits)+
      ",\"close\":"+DoubleToString(r[0].close,_Digits)+
      ",\"tick_volume\":"+IntegerToString((long)r[0].tick_volume)+
      ",\"spread\":"+IntegerToString((long)r[0].spread)+",\"source\":\"mt5-ea\"}";
   PostJson("/v1/candle", body);
}
int OnInit() {
   if(StringLen(InpBridgeToken) < 32) {
      Print("AIFX: bridge token must be at least 32 characters.");
      return INIT_PARAMETERS_INCORRECT;
   }
   EventSetTimer(MathMax(5, InpHeartbeatSeconds));
   Print("AIFX telemetry bridge started. Trading is intentionally disabled.");
   return INIT_SUCCEEDED;
}
void OnTimer() {
   SendHeartbeat();
   SendClosedCandle();
}
void OnDeinit(const int reason) { EventKillTimer(); }
// Intentionally contains no OrderSend, CTrade, PositionOpen or trade API calls.
