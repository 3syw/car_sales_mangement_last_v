import re, pathlib
path=pathlib.Path(r'c:/Users/ComputerWorld/car_sales_system/sales/views.py')
text=path.read_text(encoding='utf-8')
pattern=r"def register\(request\):[\s\S]*?return render\(request, 'sales/register.html', \{'form': form\}\)"
new='''def register(request):
        """User signup with account type field."""
        from .forms import RegistrationForm
        from django.contrib.auth import login

        if request.method == 'POST':
            form = RegistrationForm(request.POST)
            if form.is_valid():
                user = form.save()
                acct = form.cleaned_data.get('account_type')
                if hasattr(user, 'profile'):
                    user.profile.account_type = acct
                    user.profile.save()
                login(request, user)
                return redirect('dashboard')
        else:
            form = RegistrationForm()
        return render(request, 'sales/register.html', {'form': form})'''

newtext=re.sub(pattern, new, text)
path.write_text(newtext, encoding='utf-8')
print('replaced')
