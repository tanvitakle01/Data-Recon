 **VENV**: 
 .\venv\Scripts\Activate.ps1   

 **FRONTEND**: 
 cd frontend 
 npm run dev

 **BACKEND**:  
 python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 

**LATEST VERSION**
git switch recon-bot
npm run dev

**PREVIOUS VERSION**
git switch main
npm run dev

**MERGE COMMANDS**
git switch main
git merge recon-bot
git push origin main